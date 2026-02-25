from __future__ import annotations

import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


class GmailClient:

    async def collect_activities(self, access_token: str, target_date: str) -> list[dict]:
        """Collect email activities for a specific date (YYYY-MM-DD)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        activities = []

        # Convert date to Gmail query format
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        after = date_obj.strftime("%Y/%m/%d")
        next_day = date_obj.replace(day=date_obj.day + 1)
        before = next_day.strftime("%Y/%m/%d")

        try:
            async with httpx.AsyncClient() as client:
                # List messages for the day
                resp = await client.get(
                    f"{GMAIL_API}/users/me/messages",
                    headers=headers,
                    params={
                        "q": f"after:{after} before:{before}",
                        "maxResults": 50,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                messages = data.get("messages", [])
                for msg_stub in messages:
                    msg_data = await self._get_message(client, headers, msg_stub["id"])
                    if msg_data:
                        activities.append(msg_data)

        except Exception as e:
            logger.error(f"Gmail collection failed: {e}")
            raise

        return [self._to_activity(a, target_date) for a in activities]

    async def _get_message(self, client: httpx.AsyncClient, headers: dict, msg_id: str) -> dict | None:
        try:
            resp = await client.get(
                f"{GMAIL_API}/users/me/messages/{msg_id}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": "Subject,From,To,Date"},
            )
            resp.raise_for_status()
            data = resp.json()

            headers_list = data.get("payload", {}).get("headers", [])
            header_map = {h["name"]: h["value"] for h in headers_list}

            labels = data.get("labelIds", [])
            is_sent = "SENT" in labels

            return {
                "id": msg_id,
                "subject": header_map.get("Subject", "(no subject)"),
                "from": header_map.get("From", ""),
                "to": header_map.get("To", ""),
                "date": header_map.get("Date", ""),
                "snippet": data.get("snippet", ""),
                "is_sent": is_sent,
            }
        except Exception as e:
            logger.warning(f"Failed to get message {msg_id}: {e}")
            return None

    def _to_activity(self, msg: dict, report_date: str) -> dict:
        return {
            "source": "gmail",
            "activity_type": "email_sent" if msg["is_sent"] else "email_received",
            "title": msg["subject"],
            "summary": msg["snippet"][:200],
            "participants": msg["to"] if msg["is_sent"] else msg["from"],
            "activity_time": msg.get("date", f"{report_date}T00:00:00"),
            "report_date": report_date,
        }
