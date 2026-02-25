from __future__ import annotations

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from config.settings import settings

_serializer = URLSafeTimedSerializer(settings.app_secret_key)


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
        return data["user_id"]
    except (BadSignature, SignatureExpired):
        return None
