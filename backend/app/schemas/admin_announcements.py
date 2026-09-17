"""Request and response models for announcements (spec 054)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAnnouncementRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=3, max_length=4000)
    audience: str = Field(default="everyone", pattern="^(everyone|staff)$")
    #: Null sends now. A time already past also sends now — a schedule for the
    #: past is a send, and leaving it pending would help nobody.
    scheduled_for: datetime | None = None


class UpdateAnnouncementRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    body: str | None = Field(default=None, min_length=3, max_length=4000)
    scheduled_for: datetime | None = None


class AnnouncementResponse(BaseModel):
    id: UUID
    title: str
    body: str
    audience: str
    created_by_name: str | None
    scheduled_for: datetime | None
    sent_at: datetime | None
    cancelled_at: datetime | None
    recipient_count: int
    #: Counted over the fan-out rows, never stored here — read state lives on
    #: the notification, which is where it already was.
    read_count: int
    created_at: datetime
