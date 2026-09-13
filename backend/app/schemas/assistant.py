"""Request and response models for the System AI chat.

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
    #: The rung currently in force — which prompt and which gates this player
    #: faces (spec 033).
    ladder_level: int = 0
    #: The highest rung their solves have earned, and the ceiling on the
    #: selector. Derived server-side; a client that sends its own is ignored.
    max_ladder_level: int = 0


class SelectLevelRequest(BaseModel):
    #: Refused above ``max_ladder_level``. Selecting *any* level clears the
    #: conversation — a carried-over transcript keeps the previous rung's
    #: successful injections in context.
    level: int = Field(ge=0, le=5)


class SelectLevelResponse(BaseModel):
    ladder_level: int
    max_ladder_level: int
    #: Always true today, and explicit so the client need not infer it.
    conversation_cleared: bool = True


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


class FindingResponse(BaseModel):
    id: UUID
    created_at: datetime
    layer: str
    rule: str
    severity: str
    action: str
    player_name: str
    challenge_id: UUID | None
    #: The exchange, so a reviewer sees both halves. The reply is the model's
    #: real text when it was withheld — that is the point of looking.
    question: str | None
    reply: str | None
    detail: dict


class FindingsPage(BaseModel):
    findings: list[FindingResponse]
    total: int


class PurgeResponse(BaseModel):
    purged: int


class ToggleAssistantRequest(BaseModel):
    enabled: bool


class BlockPlayerRequest(BaseModel):
    blocked: bool
