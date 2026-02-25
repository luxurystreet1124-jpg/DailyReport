from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)


class ConfluenceClient:

    async def collect_activities(
        self, access_token: str, cloud_id: str, target_date: str
    ) -> list[dict]:
        """Collect Confluence page activities for a specific date (YYYY-MM-DD)."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        base_url = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
        activities = []

        try:
            async with httpx.AsyncClient() as client:
                # Get current user
                me_resp = await client.get(
                    f"{base_url}/wiki/rest/api/user/current",
                    headers=headers,
                )
                me_resp.raise_for_status()
                me = me_resp.json()
                account_id = me.get("accountId", "")

                # Search for pages modified on the target date by the user
                cql = (
                    f'lastModified = "{target_date}" '
                    f'AND contributor = "{account_id}" '
                    f'ORDER BY lastModified DESC'
                )
                resp = await client.get(
                    f"{base_url}/wiki/rest/api/content/search",
                    headers=headers,
                    params={
                        "cql": cql,
                        "limit": 50,
                        "expand": "space,history,history.lastUpdated",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for page in data.get("results", []):
                    activities.append(self._to_activity(page, account_id, target_date))

        except Exception as e:
            logger.error(f"Confluence collection failed: {e}")
            raise

        return activities

    def _to_activity(self, page: dict, account_id: str, report_date: str) -> dict:
        title = page.get("title", "(untitled)")
        space_name = page.get("space", {}).get("name", "")

        history = page.get("history", {})
        created_by = history.get("createdBy", {}).get("accountId", "")
        is_created = created_by == account_id

        last_updated = history.get("lastUpdated", {})
        updated_when = last_updated.get("when", f"{report_date}T00:00:00.000Z")

        summary = f"{'作成' if is_created else '編集'}: {title}"
        if space_name:
            summary += f" (スペース: {space_name})"

        return {
            "source": "confluence",
            "activity_type": "page_created" if is_created else "page_edited",
            "title": title,
            "summary": summary,
            "participants": json.dumps([space_name]),
            "activity_time": updated_when,
            "report_date": report_date,
        }
