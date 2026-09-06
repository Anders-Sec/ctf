"""Response models for anti-cheat signals."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SignalsResponse(BaseModel):
    counts: dict[str, int]
    findings: dict[str, list[dict[str, Any]]]


class DismissSignalRequest(BaseModel):
    signal_type: str = Field(min_length=1, max_length=64)
    subject_key: str = Field(min_length=1, max_length=64)
    #: Why it was fine. Worth recording — the next reviewer should not have to
    #: work it out again.
    note: str | None = Field(default=None, max_length=500)


class PlayerTimelineResponse(BaseModel):
    user_id: UUID
    display_name: str
    events: list[dict[str, Any]]
