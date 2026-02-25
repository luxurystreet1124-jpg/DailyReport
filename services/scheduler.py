from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

JST = timezone(timedelta(hours=9))

# 日本の祝日（年ごとに更新が必要）
JAPAN_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23",
    "2026-03-20", "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23",
    "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-23",
}


def _is_business_day(d: datetime) -> bool:
    """土日祝を除いた営業日かどうか判定。"""
    if d.weekday() >= 5:  # 土日
        return False
    if d.strftime("%Y-%m-%d") in JAPAN_HOLIDAYS_2026:
        return False
    return True


def _is_last_business_day_of_month(d: datetime) -> bool:
    """当月の最終営業日かどうか判定。"""
    if not _is_business_day(d):
        return False

    # 翌日から月末まで営業日があるか確認
    check = d + timedelta(days=1)
    while check.month == d.month:
        if _is_business_day(check):
            return False  # まだ営業日がある
        check += timedelta(days=1)

    return True


async def _run_evening_report() -> None:
    logger.info("Triggering evening report generation...")
    try:
        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        await generator.generate_all_reports("evening")
        logger.info("Evening report generation completed.")
    except Exception as e:
        logger.error(f"Evening report generation failed: {e}")


async def _run_morning_report() -> None:
    logger.info("Triggering morning report generation...")
    try:
        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        await generator.generate_all_reports("morning")
        logger.info("Morning report generation completed.")
    except Exception as e:
        logger.error(f"Morning report generation failed: {e}")


async def _run_monthly_report() -> None:
    """毎日18時にチェックし、最終営業日なら月次レポートを生成。"""
    now = datetime.now(JST)
    if not _is_last_business_day_of_month(now):
        logger.debug(f"{now.strftime('%Y-%m-%d')} is not the last business day. Skipping monthly report.")
        return

    year_month = now.strftime("%Y-%m")
    logger.info(f"Last business day detected! Generating monthly reports for {year_month}...")
    try:
        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        await generator.generate_monthly_reports(year_month)
        logger.info(f"Monthly report generation for {year_month} completed.")
    except Exception as e:
        logger.error(f"Monthly report generation failed: {e}")


def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=settings.timezone)

    _scheduler.add_job(
        _run_evening_report,
        CronTrigger(hour=settings.evening_report_hour, minute=settings.evening_report_minute),
        id="evening_report",
        name="Evening Daily Report",
        replace_existing=True,
    )

    _scheduler.add_job(
        _run_morning_report,
        CronTrigger(hour=settings.morning_report_hour, minute=settings.morning_report_minute),
        id="morning_report",
        name="Morning Daily Report",
        replace_existing=True,
    )

    # 月次レポート: 毎日18時にチェック、最終営業日のみ実行
    _scheduler.add_job(
        _run_monthly_report,
        CronTrigger(hour=18, minute=0),
        id="monthly_report",
        name="Monthly Report (last business day)",
        replace_existing=True,
    )

    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
