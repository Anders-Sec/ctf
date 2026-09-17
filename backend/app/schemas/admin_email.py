"""Request and response models for the email delivery log (spec 055)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.email import EmailKind, EmailStatus


class DeliveryResponse(BaseModel):
    id: UUID
    kind: EmailKind
    to_email: str
    user_id: UUID | None
    #: "The relay accepted it", never "it arrived" — SMTP offers no delivery
    #: confirmation, so the UI says *accepted by relay*, which is the true thing.
    status: EmailStatus
    error_type: str | None
    duration_ms: int | None
    created_at: datetime


class DeliveryPageResponse(BaseModel):
    total: int
    entries: list[DeliveryResponse]


class MailStatusResponse(BaseModel):
    configured: bool
    window_minutes: int
    sent: int
    failed: int
    failure_rate: float
    #: Worth a banner. False below a minimum volume: one failure out of one is
    #: 100% and means nothing.
    degraded: bool
