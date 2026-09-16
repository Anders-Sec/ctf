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


class CreateTemplateRequest(BaseModel):
    name: str
    image: str
    image_tag: str = "latest"
    container_port: int = 80
    protocol: str = "http"
    ttl_seconds: int = 3600
    injects_answer: bool = True
    #: One container for every challenge bound to this template (spec 046).
    shared_instance: bool = False
    readiness_path: str = "/"
    cpu_limit: str = "250m"
    memory_limit: str = "256Mi"


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
