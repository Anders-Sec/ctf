"""Request/response models for live challenge instances (spec 009)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.instance import InstanceStatus


class InstanceResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    status: InstanceStatus
    #: Present once running. Where the player points their browser.
    connection_url: str | None
    expires_at: datetime
    #: Set when provisioning failed, so the UI can say what went wrong rather
    #: than spinning forever.
    error: str | None


class AdminInstanceResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    challenge_title: str
    status: InstanceStatus
    owner_label: str
    connection_url: str | None
    created_at: datetime
    expires_at: datetime
    error: str | None
