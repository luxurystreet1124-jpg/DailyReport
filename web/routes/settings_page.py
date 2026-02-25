from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

MESSAGES = {
    "google_connected": ("Google アカウントを接続しました", "success"),
    "google_error": ("Google の接続に失敗しました", "error"),
    "slack_connected": ("Slack を接続しました", "success"),
    "slack_error": ("Slack の接続に失敗しました", "error"),
    "atlassian_connected": ("Confluence を接続しました", "success"),
    "atlassian_error": ("Confluence の接続に失敗しました", "error"),
    "invalid_state": ("認証に失敗しました。もう一度お試しください", "error"),
    "disconnected": ("サービスの接続を解除しました", "success"),
    "settings_saved": ("設定を保存しました", "success"),
}


async def _get_user(user_id: int) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, msg: str = ""):
    user_id = request.state.user_id
    user = await _get_user(user_id)

    db = await get_db()
    try:
        # Get connected services
        cursor = await db.execute(
            "SELECT service, extra_data FROM oauth_tokens WHERE user_id = ?",
            (user_id,),
        )
        tokens = {row["service"]: row for row in await cursor.fetchall()}

        flash_message = ""
        flash_type = ""
        if msg and msg in MESSAGES:
            flash_message, flash_type = MESSAGES[msg]

        return templates.TemplateResponse("settings.html", {
            "request": request,
            "user": user,
            "google_connected": "google" in tokens,
            "slack_connected": "slack" in tokens,
            "atlassian_connected": "atlassian" in tokens,
            "flash_message": flash_message,
            "flash_type": flash_type,
            "active_page": "settings",
        })
    finally:
        await db.close()


@router.post("/settings/schedule")
async def update_schedule(
    request: Request,
    report_time_evening: str = Form("21:00"),
    report_time_morning: str = Form("07:00"),
):
    user_id = request.state.user_id
    db = await get_db()
    try:
        await db.execute(
            """UPDATE users
            SET report_time_evening = ?, report_time_morning = ?, updated_at = datetime('now')
            WHERE id = ?""",
            (report_time_evening, report_time_morning, user_id),
        )
        await db.commit()
        return RedirectResponse(url="/settings?msg=settings_saved", status_code=302)
    finally:
        await db.close()


@router.delete("/api/oauth/{service}/disconnect")
async def disconnect_service(request: Request, service: str):
    user_id = request.state.user_id
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM oauth_tokens WHERE user_id = ? AND service = ?",
            (user_id, service),
        )
        await db.commit()
    finally:
        await db.close()

    return HTMLResponse(
        content="""<div class="text-sm text-green-600" hx-swap-oob="true" id="flash">
            サービスの接続を解除しました
        </div>""",
        headers={"HX-Redirect": "/settings?msg=disconnected"},
    )
