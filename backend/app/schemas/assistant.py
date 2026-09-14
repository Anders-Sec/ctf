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


class TermsResponse(BaseModel):
    """The terms of use, and whether this player has accepted them (spec 035)."""

    #: Markdown. The panel renders it with the same sanitising renderer the chat
    #: uses — it is our own file, but there is no reason to have two paths.
    text: str
    #: The hash of the file. Sent back on acceptance so a player cannot accept
    #: wording they were never shown.
    version: str
    accepted: bool


class AcceptTermsRequest(BaseModel):
    #: The version the player was actually looking at. A stale one is refused.
    version: str = Field(min_length=1, max_length=64)


class TermsSummaryResponse(BaseModel):
    version: str
    accepted: int
    outstanding: int
    #: Absent unless asked for: useful before an event, mildly
    #: surveillance-shaped during one.
    outstanding_names: list[str] | None = None


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
    #: When a staff member marked it as looked at (spec 034). Null = unreviewed.
    acknowledged_at: datetime | None = None


class FindingsPage(BaseModel):
    findings: list[FindingResponse]
    total: int


class PurgeResponse(BaseModel):
    purged: int


class ToggleAssistantRequest(BaseModel):
    enabled: bool


class BlockPlayerRequest(BaseModel):
    blocked: bool


# --- The admin console (spec 034) ------------------------------------------


class WindowResponse(BaseModel):
    turns: int
    active_sessions: int
    deflections: int
    errors: int
    median_latency_ms: int | None
    p95_latency_ms: int | None
    upstream_calls: int
    #: A level 5 turn costs five. This is the capacity figure spec 033 left
    #: visible rather than fixed.
    calls_per_turn: float | None


class RungResponse(BaseModel):
    level: int
    name: str
    turns: int
    solves: int
    #: Must stay near zero. A climb means the model has started inventing flags
    #: and players are about to submit them.
    decoys: int
    gates: dict[str, int]
    players: int


class MetricsResponse(BaseModel):
    generated_at: datetime
    windows: dict[str, WindowResponse]
    errors_by_reason: dict[str, int]
    findings_by_rule: dict[str, int]
    rungs: list[RungResponse]
    total_turns: int
    total_conversations: int
    unacknowledged_findings: int


class SessionResponse(BaseModel):
    """Metadata only — deliberately no message content."""

    user_id: UUID
    player_name: str
    turns: int
    last_message_at: datetime | None
    ladder_level: int
    findings: int
    blocked: bool
    from_staff: bool


class SessionsPage(BaseModel):
    sessions: list[SessionResponse]


class TranscriptTurnResponse(BaseModel):
    id: UUID
    role: str
    content: str
    #: What the model actually said, when a reply was withheld.
    original_content: str | None
    #: The model's scratchpad. Spec 010 stores it and returns it nowhere; this
    #: admin-only surface is the single documented exception (spec 034). On the
    #: ladder it routinely contains the flag the model was protecting.
    reasoning_content: str | None
    ladder_level: int | None
    trace: list[str] | None
    latency_ms: int | None
    upstream_calls: int | None
    error: str | None
    created_at: datetime


class TranscriptResponse(BaseModel):
    user_id: UUID
    player_name: str
    #: False when retention has purged the conversation.
    exists: bool
    turns: list[TranscriptTurnResponse]
