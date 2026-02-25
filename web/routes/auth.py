from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt

from database.db import get_db
from services.session import create_session_token

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        if not row or not bcrypt.verify(password, row["password_hash"]):
            return templates.TemplateResponse("login.html", {
                "request": request,
                "flash_message": "メールアドレスまたはパスワードが正しくありません",
                "flash_type": "error",
            })

        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(
            key="session",
            value=create_session_token(row["id"]),
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )
        return response
    finally:
        await db.close()


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if password != password_confirm:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "flash_message": "パスワードが一致しません",
            "flash_type": "error",
        })

    if len(password) < 6:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "flash_message": "パスワードは6文字以上で入力してください",
            "flash_type": "error",
        })

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
        if await cursor.fetchone():
            return templates.TemplateResponse("register.html", {
                "request": request,
                "flash_message": "このメールアドレスは既に登録されています",
                "flash_type": "error",
            })

        password_hash = bcrypt.hash(password)
        cursor = await db.execute(
            "INSERT INTO users (email, display_name, password_hash) VALUES (?, ?, ?)",
            (email, display_name, password_hash),
        )
        await db.commit()
        user_id = cursor.lastrowid

        response = RedirectResponse(url="/settings", status_code=302)
        response.set_cookie(
            key="session",
            value=create_session_token(user_id),
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )
        return response
    finally:
        await db.close()


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session")
    return response


# --- OAuth2 Routes ---

@router.get("/oauth/google/authorize")
async def google_authorize(request: Request):
    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    url = oauth.get_google_authorize_url(request.state.user_id)
    return RedirectResponse(url=url)


@router.get("/oauth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(url="/settings?msg=google_error")

    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    user_id = oauth.verify_state(state)
    if user_id is None:
        return RedirectResponse(url="/settings?msg=invalid_state")

    try:
        await oauth.exchange_google_code(user_id, code)
        return RedirectResponse(url="/settings?msg=google_connected")
    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        return RedirectResponse(url="/settings?msg=google_error")


@router.get("/oauth/slack/authorize")
async def slack_authorize(request: Request):
    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    url = oauth.get_slack_authorize_url(request.state.user_id)
    return RedirectResponse(url=url)


@router.get("/oauth/slack/callback")
async def slack_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(url="/settings?msg=slack_error")

    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    user_id = oauth.verify_state(state)
    if user_id is None:
        return RedirectResponse(url="/settings?msg=invalid_state")

    try:
        await oauth.exchange_slack_code(user_id, code)
        return RedirectResponse(url="/settings?msg=slack_connected")
    except Exception as e:
        logger.error(f"Slack OAuth error: {e}")
        return RedirectResponse(url="/settings?msg=slack_error")


@router.get("/oauth/atlassian/authorize")
async def atlassian_authorize(request: Request):
    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    url = oauth.get_atlassian_authorize_url(request.state.user_id)
    return RedirectResponse(url=url)


@router.get("/oauth/atlassian/callback")
async def atlassian_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(url="/settings?msg=atlassian_error")

    from services.oauth_manager import OAuthManager
    oauth = OAuthManager()
    user_id = oauth.verify_state(state)
    if user_id is None:
        return RedirectResponse(url="/settings?msg=invalid_state")

    try:
        await oauth.exchange_atlassian_code(user_id, code)
        return RedirectResponse(url="/settings?msg=atlassian_connected")
    except Exception as e:
        logger.error(f"Atlassian OAuth error: {e}")
        return RedirectResponse(url="/settings?msg=atlassian_error")
