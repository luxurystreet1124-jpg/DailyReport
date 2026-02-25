from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from config.settings import settings
from database.db import get_db

logger = logging.getLogger(__name__)

_serializer = URLSafeTimedSerializer(settings.app_secret_key)


class OAuthManager:

    # --- State management (CSRF) ---

    def generate_state(self, user_id: int) -> str:
        return _serializer.dumps({"user_id": user_id, "purpose": "oauth"})

    def verify_state(self, state: str) -> int | None:
        try:
            data = _serializer.loads(state, max_age=600)  # 10 min expiry
            return data.get("user_id")
        except (BadSignature, SignatureExpired):
            return None

    # --- Token storage ---

    async def store_tokens(
        self, user_id: int, service: str, access_token: str,
        refresh_token: str | None = None, expires_at: str | None = None,
        scopes: str | None = None, extra_data: str | None = None,
    ) -> None:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO oauth_tokens (user_id, service, access_token, refresh_token, expires_at, scopes, extra_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, service)
                DO UPDATE SET access_token=excluded.access_token,
                    refresh_token=COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
                    expires_at=excluded.expires_at,
                    scopes=excluded.scopes,
                    extra_data=COALESCE(excluded.extra_data, oauth_tokens.extra_data),
                    updated_at=datetime('now')""",
                (user_id, service, access_token, refresh_token, expires_at, scopes, extra_data),
            )
            await db.commit()
        finally:
            await db.close()

    async def get_token_row(self, user_id: int, service: str) -> dict | None:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM oauth_tokens WHERE user_id = ? AND service = ?",
                (user_id, service),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def get_valid_token(self, user_id: int, service: str) -> str | None:
        row = await self.get_token_row(user_id, service)
        if not row:
            return None

        # Check expiry and refresh if needed
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires < datetime.utcnow() + timedelta(minutes=5):
                if row["refresh_token"]:
                    refreshed = await self._refresh_token(user_id, service, row["refresh_token"])
                    if refreshed:
                        return refreshed
                    return None
                return None

        return row["access_token"]

    async def is_connected(self, user_id: int, service: str) -> bool:
        row = await self.get_token_row(user_id, service)
        return row is not None

    # --- Google OAuth2 ---

    def get_google_authorize_url(self, user_id: int) -> str:
        state = self.generate_state(user_id)
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(settings.google_scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def exchange_google_code(self, user_id: int, code: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        await self.store_tokens(
            user_id=user_id,
            service="google",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=json.dumps(settings.google_scopes),
        )

    # --- Slack OAuth2 ---

    def get_slack_authorize_url(self, user_id: int) -> str:
        state = self.generate_state(user_id)
        params = {
            "client_id": settings.slack_client_id,
            "redirect_uri": settings.slack_redirect_uri,
            "scope": "",
            "user_scope": settings.slack_scopes,
            "state": state,
        }
        return f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    async def exchange_slack_code(self, user_id: int, code: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "code": code,
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "redirect_uri": settings.slack_redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("ok"):
            raise Exception(f"Slack OAuth failed: {data.get('error')}")

        authed_user = data.get("authed_user", {})
        extra = {
            "team_id": data.get("team", {}).get("id"),
            "team_name": data.get("team", {}).get("name"),
            "slack_user_id": authed_user.get("id"),
        }

        await self.store_tokens(
            user_id=user_id,
            service="slack",
            access_token=authed_user.get("access_token", ""),
            refresh_token=authed_user.get("refresh_token"),
            scopes=authed_user.get("scope", ""),
            extra_data=json.dumps(extra),
        )

    # --- Atlassian OAuth2 ---

    def get_atlassian_authorize_url(self, user_id: int) -> str:
        state = self.generate_state(user_id)
        params = {
            "audience": "api.atlassian.com",
            "client_id": settings.atlassian_client_id,
            "scope": settings.atlassian_scopes,
            "redirect_uri": settings.atlassian_redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        return f"https://auth.atlassian.com/authorize?{urlencode(params)}"

    async def exchange_atlassian_code(self, user_id: int, code: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://auth.atlassian.com/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": settings.atlassian_client_id,
                    "client_secret": settings.atlassian_client_secret,
                    "code": code,
                    "redirect_uri": settings.atlassian_redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()

        # Get accessible resources (cloud ID)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
            resp.raise_for_status()
            resources = resp.json()

        cloud_id = resources[0]["id"] if resources else ""
        site_url = resources[0].get("url", "") if resources else ""

        extra = {"cloud_id": cloud_id, "site_url": site_url}

        await self.store_tokens(
            user_id=user_id,
            service="atlassian",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=settings.atlassian_scopes,
            extra_data=json.dumps(extra),
        )

    # --- Token refresh ---

    async def _refresh_token(self, user_id: int, service: str, refresh_token: str) -> str | None:
        try:
            if service == "google":
                return await self._refresh_google(user_id, refresh_token)
            elif service == "atlassian":
                return await self._refresh_atlassian(user_id, refresh_token)
            # Slack user tokens typically don't expire
            return None
        except Exception as e:
            logger.error(f"Token refresh failed for {service}: {e}")
            return None

    async def _refresh_google(self, user_id: int, refresh_token: str) -> str | None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        await self.store_tokens(
            user_id=user_id, service="google",
            access_token=data["access_token"],
            expires_at=expires_at,
        )
        return data["access_token"]

    async def _refresh_atlassian(self, user_id: int, refresh_token: str) -> str | None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://auth.atlassian.com/oauth/token",
                json={
                    "grant_type": "refresh_token",
                    "client_id": settings.atlassian_client_id,
                    "client_secret": settings.atlassian_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        await self.store_tokens(
            user_id=user_id, service="atlassian",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
        )
        return data["access_token"]
