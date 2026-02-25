from __future__ import annotations

import json
import logging
import time

from database.db import get_db
from services.oauth_manager import OAuthManager
from services.gmail_client import GmailClient
from services.calendar_client import CalendarClient
from services.slack_client import SlackClient
from services.confluence_client import ConfluenceClient

logger = logging.getLogger(__name__)


class ActivityCollector:

    def __init__(self) -> None:
        self.oauth = OAuthManager()
        self.gmail = GmailClient()
        self.calendar = CalendarClient()
        self.slack = SlackClient()
        self.confluence = ConfluenceClient()

    async def collect_user_activities(self, user_id: int, target_date: str) -> list[dict]:
        """Collect activities from all connected services for a user.

        Each service collection is independent -- if one fails, others proceed.
        """
        activities = []
        errors = []

        # Google (Gmail + Calendar)
        google_token = await self.oauth.get_valid_token(user_id, "google")
        if google_token:
            activities, errors = await self._collect_google(
                google_token, target_date, user_id, activities, errors
            )

        # Slack
        slack_token = await self.oauth.get_valid_token(user_id, "slack")
        if slack_token:
            try:
                start = time.time()
                slack_activities = await self.slack.collect_activities(slack_token, target_date)
                activities.extend(slack_activities)
                await self._log_pipeline(
                    user_id, "collect_slack", "success",
                    execution_time_ms=int((time.time() - start) * 1000),
                )
            except Exception as e:
                errors.append(("slack", str(e)))
                await self._log_pipeline(user_id, "collect_slack", "error", str(e))

        # Confluence
        atlassian_token = await self.oauth.get_valid_token(user_id, "atlassian")
        if atlassian_token:
            try:
                token_row = await self.oauth.get_token_row(user_id, "atlassian")
                extra = json.loads(token_row["extra_data"]) if token_row and token_row["extra_data"] else {}
                cloud_id = extra.get("cloud_id", "")
                if cloud_id:
                    start = time.time()
                    confluence_activities = await self.confluence.collect_activities(
                        atlassian_token, cloud_id, target_date
                    )
                    activities.extend(confluence_activities)
                    await self._log_pipeline(
                        user_id, "collect_confluence", "success",
                        execution_time_ms=int((time.time() - start) * 1000),
                    )
            except Exception as e:
                errors.append(("confluence", str(e)))
                await self._log_pipeline(user_id, "collect_confluence", "error", str(e))

        # Store activities in database
        await self._store_activities(user_id, activities, target_date)

        if errors:
            logger.warning(f"Collection errors for user {user_id}: {errors}")

        return activities

    async def _collect_google(
        self, token: str, target_date: str, user_id: int,
        activities: list[dict], errors: list[tuple],
    ) -> tuple[list[dict], list[tuple]]:
        # Gmail
        try:
            start = time.time()
            gmail_activities = await self.gmail.collect_activities(token, target_date)
            activities.extend(gmail_activities)
            await self._log_pipeline(
                user_id, "collect_gmail", "success",
                execution_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            errors.append(("gmail", str(e)))
            await self._log_pipeline(user_id, "collect_gmail", "error", str(e))

        # Calendar
        try:
            start = time.time()
            calendar_activities = await self.calendar.collect_activities(token, target_date)
            activities.extend(calendar_activities)
            await self._log_pipeline(
                user_id, "collect_calendar", "success",
                execution_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            errors.append(("calendar", str(e)))
            await self._log_pipeline(user_id, "collect_calendar", "error", str(e))

        return activities, errors

    async def _store_activities(self, user_id: int, activities: list[dict], report_date: str) -> None:
        if not activities:
            return

        db = await get_db()
        try:
            # Delete existing activities for this user+date to avoid duplicates
            await db.execute(
                "DELETE FROM activity_logs WHERE user_id = ? AND report_date = ?",
                (user_id, report_date),
            )

            for a in activities:
                await db.execute(
                    """INSERT INTO activity_logs
                    (user_id, source, activity_type, title, summary, participants, activity_time, report_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        a.get("source", ""),
                        a.get("activity_type", ""),
                        a.get("title", ""),
                        a.get("summary", ""),
                        a.get("participants", ""),
                        a.get("activity_time", ""),
                        report_date,
                    ),
                )
            await db.commit()
        finally:
            await db.close()

    async def _log_pipeline(
        self, user_id: int, action: str, status: str,
        error_message: str | None = None, execution_time_ms: int | None = None,
    ) -> None:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO pipeline_logs (user_id, action, status, error_message, execution_time_ms)
                VALUES (?, ?, ?, ?, ?)""",
                (user_id, action, status, error_message, execution_time_ms),
            )
            await db.commit()
        finally:
            await db.close()
