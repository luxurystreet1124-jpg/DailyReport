from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class CalendarClient:

    async def collect_activities(self, access_token: str, target_date: str) -> list[dict]:
        """Collect calendar events for a specific date (YYYY-MM-DD)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        activities = []

        time_min = f"{target_date}T00:00:00+09:00"
        time_max = f"{target_date}T23:59:59+09:00"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{CALENDAR_API}/calendars/primary/events",
                    headers=headers,
                    params={
                        "timeMin": time_min,
                        "timeMax": time_max,
                        "singleEvents": "true",
                        "orderBy": "startTime",
                        "maxResults": 50,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for event in data.get("items", []):
                    # Skip declined events
                    attendees = event.get("attendees", [])
                    self_attendee = next(
                        (a for a in attendees if a.get("self")), None
                    )
                    if self_attendee and self_attendee.get("responseStatus") == "declined":
                        continue

                    activities.append(self._to_activity(event, target_date))

        except Exception as e:
            logger.error(f"Calendar collection failed: {e}")
            raise

        return activities

    def _to_activity(self, event: dict, report_date: str) -> dict:
        start = event.get("start", {})
        start_time = start.get("dateTime", start.get("date", f"{report_date}T00:00:00"))

        end = event.get("end", {})
        end_time = end.get("dateTime", end.get("date", ""))

        attendees = event.get("attendees", [])
        participant_names = [
            a.get("displayName", a.get("email", ""))
            for a in attendees
            if not a.get("self")
        ]

        summary = event.get("summary", "(no title)")
        description = event.get("description", "")[:200] if event.get("description") else ""
        location = event.get("location", "")

        time_info = ""
        if "T" in start_time and end_time and "T" in end_time:
            s = start_time[11:16]
            e = end_time[11:16]
            time_info = f"{s}-{e}"

        activity_summary = f"{time_info} {summary}".strip()
        if location:
            activity_summary += f" ({location})"

        return {
            "source": "calendar",
            "activity_type": "meeting",
            "title": summary,
            "summary": activity_summary,
            "participants": json.dumps(participant_names),
            "activity_time": start_time,
            "report_date": report_date,
        }
