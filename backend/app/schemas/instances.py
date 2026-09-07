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


class CreateTemplateRequest(BaseModel):
    name: str
    image: str
    image_tag: str = "latest"
    container_port: int = 80
    protocol: str = "http"
    ttl_seconds: int = 3600
    injects_answer: bool = True
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
