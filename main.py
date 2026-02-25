from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from config.settings import settings
from database.db import init_db
from services.session import verify_session_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_PATHS = {"/login", "/register", "/oauth"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()

    # Start scheduler
    try:
        from services.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler started.")
    except Exception as e:
        logger.warning(f"Scheduler start failed (non-critical): {e}")

    yield

    # Shutdown scheduler
    try:
        from services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(title="DailyReport", lifespan=lifespan)

templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Allow public paths
    if any(path.startswith(p) for p in PUBLIC_PATHS):
        response = await call_next(request)
        return response

    # Check session
    session_token = request.cookies.get("session")
    if not session_token:
        return RedirectResponse(url="/login", status_code=302)

    user_id = verify_session_token(session_token)
    if user_id is None:
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie("session")
        return response

    request.state.user_id = user_id
    response = await call_next(request)
    return response


# Register routes
from web.routes.auth import router as auth_router
from web.routes.dashboard import router as dashboard_router
from web.routes.reports import router as reports_router
from web.routes.settings_page import router as settings_router

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(settings_router)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard", status_code=302)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
