from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
JST = timezone(timedelta(hours=9))


class SlackClient:

    async def collect_activities(self, access_token: str, target_date: str) -> list[dict]:
        """Collect Slack message activities for a specific date (YYYY-MM-DD)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        activities = []

        date_obj = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=JST)
        oldest = str(int(date_obj.timestamp()))
        latest = str(int((date_obj + timedelta(days=1)).timestamp()))

        try:
            async with httpx.AsyncClient() as client:
                # Get user ID
                user_resp = await client.get(
                    f"{SLACK_API}/auth.test",
                    headers=headers,
                )
                user_resp.raise_for_status()
                user_data = user_resp.json()
                if not user_data.get("ok"):
                    raise Exception(f"Slack auth.test failed: {user_data.get('error')}")
                my_user_id = user_data["user_id"]

                # Get channels
                channels = await self._get_channels(client, headers)

                # Get messages from each channel
                for channel in channels[:20]:  # Limit to 20 channels
                    msgs = await self._get_channel_messages(
                        client, headers, channel, oldest, latest, my_user_id
                    )
                    for msg in msgs:
                        activities.append(
                            self._to_activity(msg, channel, target_date)
                        )

        except Exception as e:
            logger.error(f"Slack collection failed: {e}")
            raise

        return activities

    async def _get_channels(self, client: httpx.AsyncClient, headers: dict) -> list[dict]:
        channels = []
        cursor = ""
        for _ in range(3):  # Max 3 pages
            params = {"types": "public_channel,private_channel", "limit": 100}
            if cursor:
                params["cursor"] = cursor

            resp = await client.get(f"{SLACK_API}/conversations.list", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                break

            for ch in data.get("channels", []):
                if ch.get("is_member"):
                    channels.append({
                        "id": ch["id"],
                        "name": ch.get("name", "unknown"),
                    })

            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return channels

    async def _get_channel_messages(
        self, client: httpx.AsyncClient, headers: dict,
        channel: dict, oldest: str, latest: str, my_user_id: str,
    ) -> list[dict]:
        try:
            resp = await client.get(
                f"{SLACK_API}/conversations.history",
                headers=headers,
                params={
                    "channel": channel["id"],
                    "oldest": oldest,
                    "latest": latest,
                    "limit": 100,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                return []

            # Filter to user's messages only
            return [
                msg for msg in data.get("messages", [])
                if msg.get("user") == my_user_id
                and msg.get("subtype") is None  # Skip system messages
            ]
        except Exception as e:
            logger.warning(f"Failed to get messages from {channel['name']}: {e}")
            return []

    def _to_activity(self, msg: dict, channel: dict, report_date: str) -> dict:
        ts = float(msg.get("ts", "0"))
        msg_time = datetime.fromtimestamp(ts, tz=JST)

        text = msg.get("text", "")[:200]

        return {
            "source": "slack",
            "activity_type": "message",
            "title": f"#{channel['name']}",
            "summary": text,
            "participants": json.dumps([channel["name"]]),
            "activity_time": msg_time.isoformat(),
            "report_date": report_date,
        }
