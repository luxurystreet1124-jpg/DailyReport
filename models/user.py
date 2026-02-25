from __future__ import annotations

from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str
    display_name: str
    password_hash: str
    report_time_evening: str = "21:00"
    report_time_morning: str = "07:00"
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> User:
        return cls(**dict(row))


class UserCreate(BaseModel):
    email: str
    display_name: str
    password: str


class OAuthToken(BaseModel):
    id: int
    user_id: int
    service: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: str | None = None
    scopes: str | None = None
    extra_data: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> OAuthToken:
        return cls(**dict(row))
