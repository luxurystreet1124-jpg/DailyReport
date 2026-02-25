from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import markdown

from database.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


async def _get_user(user_id: int) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int):
    user_id = request.state.user_id
    user = await _get_user(user_id)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM daily_reports WHERE id = ? AND user_id = ?",
            (report_id, user_id),
        )
        report = await cursor.fetchone()
        if not report:
            return RedirectResponse(url="/dashboard", status_code=302)

        report = dict(report)
        report["content_html"] = markdown.markdown(
            report["content"],
            extensions=["tables", "fenced_code"],
        )

        # Get activity logs for this report
        cursor = await db.execute(
            """SELECT * FROM activity_logs
            WHERE user_id = ? AND report_date = ?
            ORDER BY activity_time DESC""",
            (user_id, report["report_date"]),
        )
        activities = [dict(row) for row in await cursor.fetchall()]

        return templates.TemplateResponse("report_detail.html", {
            "request": request,
            "user": user,
            "report": report,
            "activities": activities,
            "active_page": "dashboard",
        })
    finally:
        await db.close()


@router.post("/reports/{report_id}/edit")
async def edit_report(request: Request, report_id: int, content: str = Form(...)):
    user_id = request.state.user_id
    db = await get_db()
    try:
        await db.execute(
            """UPDATE daily_reports
            SET content = ?, status = 'edited', updated_at = datetime('now')
            WHERE id = ? AND user_id = ?""",
            (content, report_id, user_id),
        )
        await db.commit()
        return RedirectResponse(url=f"/reports/{report_id}", status_code=302)
    finally:
        await db.close()


@router.post("/reports/generate", response_class=HTMLResponse)
async def generate_report_now(request: Request):
    user_id = request.state.user_id
    try:
        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        report = await generator.generate_user_report(user_id, "evening")
        if report:
            return RedirectResponse(url=f"/reports/{report['id']}", status_code=302)
        return RedirectResponse(url="/dashboard?msg=no_activities", status_code=302)
    except Exception as e:
        logger.error(f"Manual report generation failed: {e}")
        return RedirectResponse(url="/dashboard?msg=generation_error", status_code=302)


@router.post("/reports/generate-monthly", response_class=HTMLResponse)
async def generate_monthly_now(request: Request):
    user_id = request.state.user_id
    try:
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        year_month = datetime.now(JST).strftime("%Y-%m")

        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        report = await generator.generate_user_monthly_report(user_id, year_month)
        if report:
            return RedirectResponse(url=f"/reports/{report['id']}", status_code=302)
        return RedirectResponse(url="/dashboard?msg=no_daily_reports", status_code=302)
    except Exception as e:
        logger.error(f"Monthly report generation failed: {e}")
        return RedirectResponse(url="/dashboard?msg=generation_error", status_code=302)


@router.post("/reports/{report_id}/regenerate")
async def regenerate_report(request: Request, report_id: int):
    user_id = request.state.user_id

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT report_date, report_type FROM daily_reports WHERE id = ? AND user_id = ?",
            (report_id, user_id),
        )
        report = await cursor.fetchone()
        if not report:
            return RedirectResponse(url="/dashboard", status_code=302)
    finally:
        await db.close()

    try:
        from pipeline.report_generator import ReportGenerator
        generator = ReportGenerator()
        new_report = await generator.generate_user_report(
            user_id, report["report_type"], target_date=report["report_date"]
        )
        if new_report:
            return RedirectResponse(url=f"/reports/{new_report['id']}", status_code=302)
    except Exception as e:
        logger.error(f"Report regeneration failed: {e}")

    return RedirectResponse(url=f"/reports/{report_id}?msg=regeneration_error", status_code=302)
