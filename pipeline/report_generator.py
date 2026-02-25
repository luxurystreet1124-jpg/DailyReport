from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from database.db import get_db
from pipeline.collector import ActivityCollector
from services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


class ReportGenerator:

    def __init__(self) -> None:
        self.collector = ActivityCollector()
        self.claude = ClaudeClient()

    async def generate_all_reports(self, report_type: str) -> None:
        """Generate reports for all active users."""
        users = await self._get_active_users()
        logger.info(f"Generating {report_type} reports for {len(users)} users...")

        for user in users:
            try:
                await self.generate_user_report(user["id"], report_type)
            except Exception as e:
                logger.error(f"Report generation failed for user {user['id']}: {e}")
                await self._log_pipeline(user["id"], "generate_report", "error", str(e))

    async def generate_user_report(
        self, user_id: int, report_type: str, target_date: str | None = None,
    ) -> dict | None:
        """Generate a single user's daily report."""
        if target_date is None:
            target_date = self._get_target_date(report_type)

        user = await self._get_user(user_id)
        if not user:
            return None

        logger.info(f"Generating {report_type} report for {user['display_name']} ({target_date})")

        # 1. Collect activities
        if report_type == "morning":
            # 朝レポート: 直近3日分の活動 + 本日のカレンダー予定
            all_activities = await self._collect_morning_data(user_id, target_date)
        else:
            # 夕方レポート: 当日の活動のみ
            all_activities = await self.collector.collect_user_activities(user_id, target_date)
        activities = all_activities

        # 2. Generate report via Claude
        start_time = time.time()
        try:
            if all_activities:
                content = await self.claude.generate_report(
                    activities=all_activities,
                    report_type=report_type,
                    user_name=user["display_name"],
                    report_date=target_date,
                )
            else:
                content = self._empty_report(report_type, target_date)

            generation_ms = int((time.time() - start_time) * 1000)
        except Exception as e:
            logger.error(f"Claude generation failed: {e}")
            content = f"日報の自動生成に失敗しました。\n\nエラー: {e}"
            generation_ms = int((time.time() - start_time) * 1000)
            return await self._store_report(
                user_id, target_date, report_type, content,
                len(activities), [], generation_ms, status="failed",
            )

        # 3. Store report
        sources = list(set(a.get("source", "") for a in activities))
        report = await self._store_report(
            user_id, target_date, report_type, content,
            len(activities), sources, generation_ms,
        )

        await self._log_pipeline(
            user_id, "generate_report", "success",
            execution_time_ms=generation_ms,
        )

        return report

    async def _collect_morning_data(self, user_id: int, target_date: str) -> list[dict]:
        """朝レポート用: 直近3日分の活動データ + 本日のカレンダー予定を取得"""
        from services.oauth_manager import OAuthManager
        from services.calendar_client import CalendarClient

        all_activities = []

        # 直近3日分の活動を取得（前日、2日前、3日前）
        base_date = datetime.strptime(target_date, "%Y-%m-%d")
        for days_ago in range(3):
            day = (base_date - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            try:
                day_activities = await self.collector.collect_user_activities(user_id, day)
                for a in day_activities:
                    if days_ago == 0:
                        a["summary"] = f"[前日] {a.get('summary', '')}"
                    else:
                        a["summary"] = f"[{days_ago + 1}日前] {a.get('summary', '')}"
                all_activities.extend(day_activities)
            except Exception as e:
                logger.warning(f"Failed to collect activities for {day}: {e}")

        # 本日のカレンダー予定を取得
        today = datetime.now(JST).strftime("%Y-%m-%d")
        oauth = OAuthManager()
        google_token = await oauth.get_valid_token(user_id, "google")
        if google_token:
            try:
                cal = CalendarClient()
                today_events = await cal.collect_activities(google_token, today)
                for e in today_events:
                    e["summary"] = f"[本日の予定] {e.get('summary', '')}"
                all_activities.extend(today_events)
            except Exception as e:
                logger.warning(f"Failed to get today's calendar: {e}")

        return all_activities

    async def generate_monthly_reports(self, year_month: str | None = None) -> None:
        """全ユーザーの月次レポート（月間まとめ + 翌月タスク）を生成。"""
        if year_month is None:
            year_month = datetime.now(JST).strftime("%Y-%m")

        users = await self._get_active_users()
        logger.info(f"Generating monthly reports for {year_month}, {len(users)} users...")

        for user in users:
            try:
                await self.generate_user_monthly_report(user["id"], year_month)
            except Exception as e:
                logger.error(f"Monthly report failed for user {user['id']}: {e}")
                await self._log_pipeline(user["id"], "generate_monthly", "error", str(e))

    async def generate_user_monthly_report(self, user_id: int, year_month: str) -> dict | None:
        """1ユーザーの月次レポート（月間まとめ + 翌月タスク）を生成。"""
        user = await self._get_user(user_id)
        if not user:
            return None

        logger.info(f"Generating monthly reports for {user['display_name']} ({year_month})")

        # 当月の日次レポートを全て取得
        daily_reports = await self._get_monthly_daily_reports(user_id, year_month)

        if not daily_reports:
            logger.warning(f"No daily reports found for {year_month}")
            return None

        # 日次レポートをアクティビティ形式に変換
        report_activities = []
        for r in daily_reports:
            report_activities.append({
                "source": "daily_report",
                "activity_type": r["report_type"],
                "title": f"{r['report_date']} ({r['report_type']})",
                "summary": r["content"][:500],
                "participants": "",
                "activity_time": r["report_date"],
                "report_date": r["report_date"],
            })

        report_date = f"{year_month}-01"

        # 1. 月間まとめレポート
        start_time = time.time()
        try:
            summary_content = await self.claude.generate_report(
                activities=report_activities,
                report_type="monthly_summary",
                user_name=user["display_name"],
                report_date=year_month,
            )
            gen_ms = int((time.time() - start_time) * 1000)
        except Exception as e:
            logger.error(f"Monthly summary failed: {e}")
            summary_content = f"月間レポートの生成に失敗しました。\n\nエラー: {e}"
            gen_ms = int((time.time() - start_time) * 1000)

        summary_report = await self._store_report(
            user_id, report_date, "monthly_summary", summary_content,
            len(daily_reports), ["daily_report"], gen_ms,
        )

        # 2. 翌月タスクレポート
        start_time = time.time()
        try:
            tasks_content = await self.claude.generate_report(
                activities=report_activities,
                report_type="monthly_tasks",
                user_name=user["display_name"],
                report_date=year_month,
            )
            gen_ms = int((time.time() - start_time) * 1000)
        except Exception as e:
            logger.error(f"Monthly tasks failed: {e}")
            tasks_content = f"翌月タスクレポートの生成に失敗しました。\n\nエラー: {e}"
            gen_ms = int((time.time() - start_time) * 1000)

        await self._store_report(
            user_id, report_date, "monthly_tasks", tasks_content,
            len(daily_reports), ["daily_report"], gen_ms,
        )

        await self._log_pipeline(user_id, "generate_monthly", "success")
        return summary_report

    async def _get_monthly_daily_reports(self, user_id: int, year_month: str) -> list[dict]:
        """当月の日次レポートを全て取得する。"""
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT * FROM daily_reports
                WHERE user_id = ? AND report_date LIKE ? AND report_type IN ('evening', 'morning')
                ORDER BY report_date ASC, report_type ASC""",
                (user_id, f"{year_month}%"),
            )
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

    def _get_target_date(self, report_type: str) -> str:
        now = datetime.now(JST)
        if report_type == "morning":
            target = now - timedelta(days=1)
        else:
            target = now
        return target.strftime("%Y-%m-%d")

    def _empty_report(self, report_type: str, report_date: str) -> str:
        return f"""### 業務報告 - {report_date}

本日は接続されたサービスからアクティビティが検出されませんでした。

サービスが正しく接続されているか、設定ページをご確認ください。
"""

    async def _store_report(
        self, user_id: int, report_date: str, report_type: str,
        content: str, activity_count: int, sources: list[str],
        generation_time_ms: int, status: str = "generated",
    ) -> dict:
        db = await get_db()
        try:
            # Upsert: replace existing report for same date+type
            await db.execute(
                """INSERT INTO daily_reports
                (user_id, report_date, report_type, content, activity_count, sources_used, status, generation_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, report_date, report_type)
                DO UPDATE SET content=excluded.content,
                    activity_count=excluded.activity_count,
                    sources_used=excluded.sources_used,
                    status=excluded.status,
                    generation_time_ms=excluded.generation_time_ms,
                    updated_at=datetime('now')""",
                (user_id, report_date, report_type, content, activity_count,
                 json.dumps(sources), status, generation_time_ms),
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM daily_reports WHERE user_id = ? AND report_date = ? AND report_type = ?",
                (user_id, report_date, report_type),
            )
            row = await cursor.fetchone()
            return dict(row) if row else {}
        finally:
            await db.close()

    async def _get_active_users(self) -> list[dict]:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM users WHERE is_active = 1")
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

    async def _get_user(self, user_id: int) -> dict | None:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
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
