"""Request/response models for live challenge instances (spec 009)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

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
    #: How many *other* published challenges this container also serves (046).
    #: Zero for an ordinary template, so the panel is unchanged for those.
    shared_challenge_count: int = 0


class AdminInstanceResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    challenge_title: str
    #: Which image this is, so one container owned by a party that has solved
    #: three challenges reads as correct rather than as a leak (spec 046).
    template_name: str | None
    status: InstanceStatus
    owner_label: str
    connection_url: str | None
    created_at: datetime
    expires_at: datetime
    error: str | None


#: A lifetime below this is almost certainly a typo, and a very short one is
#: indistinguishable from a broken container: the expiry reconciler destroys the
#: instance within its next 30-second tick and the player watches their target
#: vanish. A zero — which is what an emptied number field sends — did exactly
#: that at the event, so the floor is enforced here rather than trusted to the UI.
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86_400


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    image: str = Field(min_length=1, max_length=300)
    image_tag: str = Field(default="latest", min_length=1, max_length=120)
    container_port: int = Field(default=80, ge=1, le=65535)
    protocol: str = "http"
    ttl_seconds: int = Field(default=3600, ge=MIN_TTL_SECONDS, le=MAX_TTL_SECONDS)
    injects_answer: bool = True
    #: One container for every challenge bound to this template (spec 046).
    shared_instance: bool = False
    readiness_path: str = Field(default="/", min_length=1, max_length=200)
    cpu_limit: str = Field(default="250m", min_length=1, max_length=16)
    memory_limit: str = Field(default="256Mi", min_length=1, max_length=16)


class TemplateResponse(BaseModel):
    id: UUID
    name: str
    image: str
    image_tag: str
    container_port: int
    protocol: str
    ttl_seconds: int
    injects_answer: bool
    shared_instance: bool
    cpu_limit: str
    memory_limit: str
