from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class ReportType(str, Enum):
    EVENING = "evening"
    MORNING = "morning"


class ReportStatus(str, Enum):
    GENERATED = "generated"
    EDITED = "edited"
    FAILED = "failed"


class DailyReport(BaseModel):
    id: int
    user_id: int
    report_date: str
    report_type: str
    content: str
    activity_count: int = 0
    sources_used: str | None = None
    status: str = "generated"
    generation_time_ms: int | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> DailyReport:
        return cls(**dict(row))
