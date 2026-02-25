from __future__ import annotations

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from database.db import get_db

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


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_id = request.state.user_id
    user = await _get_user(user_id)

    db = await get_db()
    try:
        # Get recent reports
        cursor = await db.execute(
            """SELECT * FROM daily_reports
            WHERE user_id = ?
            ORDER BY report_date DESC, report_type DESC
            LIMIT 20""",
            (user_id,),
        )
        reports = [dict(row) for row in await cursor.fetchall()]

        # Stats
        cursor = await db.execute(
            "SELECT COUNT(*) as total FROM daily_reports WHERE user_id = ?",
            (user_id,),
        )
        total_reports = (await cursor.fetchone())["total"]

        cursor = await db.execute(
            """SELECT COUNT(DISTINCT service) as count FROM oauth_tokens
            WHERE user_id = ?""",
            (user_id,),
        )
        connected_services = (await cursor.fetchone())["count"]

        cursor = await db.execute(
            """SELECT COUNT(*) as count FROM daily_reports
            WHERE user_id = ? AND report_date >= date('now', '-7 days')""",
            (user_id,),
        )
        week_reports = (await cursor.fetchone())["count"]

        cursor = await db.execute(
            """SELECT COALESCE(AVG(activity_count), 0) as avg_count
            FROM daily_reports WHERE user_id = ?""",
            (user_id,),
        )
        avg_activities = round((await cursor.fetchone())["avg_count"], 1)

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": user,
            "reports": reports,
            "total_reports": total_reports,
            "connected_services": connected_services,
            "week_reports": week_reports,
            "avg_activities": avg_activities,
            "active_page": "dashboard",
        })
    finally:
        await db.close()
