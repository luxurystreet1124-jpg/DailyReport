from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class ActivitySource(str, Enum):
    GMAIL = "gmail"
    SLACK = "slack"
    CALENDAR = "calendar"
    CONFLUENCE = "confluence"


class ActivityType(str, Enum):
    EMAIL_SENT = "email_sent"
    EMAIL_RECEIVED = "email_received"
    MESSAGE = "message"
    MEETING = "meeting"
    PAGE_CREATED = "page_created"
    PAGE_EDITED = "page_edited"


class ActivityLog(BaseModel):
    id: int | None = None
    user_id: int
    source: str
    activity_type: str
    title: str | None = None
    summary: str | None = None
    participants: str | None = None
    raw_data: str | None = None
    activity_time: str
    report_date: str
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> ActivityLog:
        return cls(**dict(row))
