"""The dungeon master chat.

**Staff-gated for now.** Spec 010 ships the mediator; spec 011 adds both
guardrail layers and opens it to players. Shipping an unguarded assistant to 200
people in the interim would be the wrong shape of mistake, so the gate below is
deliberately one name changed in one place.
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import AppSettings, DbSession, RedisClient, Staff
from app.models.assistant import AssistantMessage
from app.schemas.assistant import (
    AssistantHealthResponse,
    AssistantMessageResponse,
    ConversationResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import ai_client
from app.services import assistant_chat as chat
from app.services.rate_limit import RateLimited, check_assistant_limits

#: Spec 011 changes this to `Player`. Everything else stays as it is.
ChatUser = Staff

router = APIRouter(tags=["assistant"])


def _message(row: AssistantMessage) -> AssistantMessageResponse:
    """Note the fields chosen. ``reasoning_content`` is not among them, by design."""
    return AssistantMessageResponse(
        id=row.id,
        role=row.role,
        content=row.content,
        challenge_id=row.challenge_id,
        created_at=row.created_at,
        error=row.error,
    )


@router.get("/assistant/conversation")
async def get_conversation(
    db: DbSession, settings: AppSettings, current: ChatUser
) -> ConversationResponse:
    history = await chat.history_for(db, current.user.id, settings.ai_history_turns * 2)
    return ConversationResponse(
        available=settings.ai_configured,
        messages=[_message(row) for row in history],
    )


@router.post("/assistant/messages")
async def send_message(
    payload: SendMessageRequest,
    db: DbSession,
    settings: AppSettings,
    redis: RedisClient,
    current: ChatUser,
) -> SendMessageResponse:
    decision = await check_assistant_limits(
        redis,
        current.user.id,
        settings.ai_messages_per_minute,
        settings.ai_messages_per_hour,
    )
    if not decision.allowed:
        raise RateLimited(
            "The dungeon master needs a moment. Ask again shortly.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )

    answer = await chat.send(
        db,
        settings,
        current.user,
        payload.content,
        payload.challenge_id,
        datetime.now(UTC),
    )
    return SendMessageResponse(message=_message(answer))


@router.delete("/assistant/conversation", status_code=204)
async def clear_conversation(db: DbSession, current: ChatUser) -> None:
    await chat.clear(db, current.user.id)


@router.get("/admin/assistant/health", tags=["admin"])
async def assistant_health(settings: AppSettings, current: Staff) -> AssistantHealthResponse:
    """Reachability at a glance, beside the other dependency panels in spec 006."""
    state = await ai_client.health(settings)
    return AssistantHealthResponse(
        enabled=state.enabled,
        configured=state.configured,
        reachable=state.reachable,
        model=state.model,
        breaker_open=state.breaker_open,
        consecutive_failures=state.consecutive_failures,
        retry_after_seconds=state.retry_after_seconds,
        in_flight=state.in_flight,
        average_latency_ms=state.average_latency_ms,
        error=state.error,
    )
