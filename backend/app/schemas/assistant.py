"""Request and response models for the dungeon master chat.

Note what is not here: ``reasoning_content`` has no field on any response model.
The model's scratchpad is kept for review and never leaves the server, and the
cleanest way to guarantee that is for the shape the client receives to have
nowhere to put it.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.assistant import MessageRole

MAX_MESSAGE_LENGTH = 2000


class AssistantMessageResponse(BaseModel):
    id: UUID
    role: MessageRole
    content: str
    challenge_id: UUID | None
    created_at: datetime
    #: Present when the model could not answer, so the UI can style the bubble
    #: as a hiccup rather than as the dungeon master's considered opinion.
    error: str | None = None


class ConversationResponse(BaseModel):
    #: False when the feature is switched off or unconfigured, so the SPA hides
    #: the chat rather than offering a button that fails.
    available: bool
    messages: list[AssistantMessageResponse]


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    #: What the player is looking at. Optional — general chat is fine.
    challenge_id: UUID | None = None


class SendMessageResponse(BaseModel):
    message: AssistantMessageResponse


class AssistantHealthResponse(BaseModel):
    enabled: bool
    configured: bool
    reachable: bool
    model: str | None
    breaker_open: bool
    consecutive_failures: int
    retry_after_seconds: int
    in_flight: int
    average_latency_ms: int | None
    error: str | None
