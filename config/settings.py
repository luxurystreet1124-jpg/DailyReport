from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Application
    app_secret_key: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    # Claude API
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Google OAuth2
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
    google_redirect_uri: str = ""

    # Slack OAuth2
    slack_client_id: str = os.getenv("SLACK_CLIENT_ID", "")
    slack_client_secret: str = os.getenv("SLACK_CLIENT_SECRET", "")
    slack_scopes: str = "channels:history,channels:read,groups:history,groups:read,im:history,im:read,users:read"
    slack_redirect_uri: str = ""

    # Atlassian OAuth2
    atlassian_client_id: str = os.getenv("ATLASSIAN_CLIENT_ID", "")
    atlassian_client_secret: str = os.getenv("ATLASSIAN_CLIENT_SECRET", "")
    atlassian_scopes: str = "read:confluence-content.all read:confluence-user offline_access"
    atlassian_redirect_uri: str = ""

    # Database
    db_path: str = os.getenv("DB_PATH", "daily_report.db")

    # Schedule
    timezone: str = "Asia/Tokyo"
    evening_report_hour: int = 21
    evening_report_minute: int = 0
    morning_report_hour: int = 7
    morning_report_minute: int = 0

    # Session
    session_max_age: int = 86400 * 7  # 7 days

    def __init__(self) -> None:
        self.google_redirect_uri = f"{self.app_base_url}/oauth/google/callback"
        self.slack_redirect_uri = f"{self.app_base_url}/oauth/slack/callback"
        self.atlassian_redirect_uri = f"{self.app_base_url}/oauth/atlassian/callback"


settings = Settings()
