"""The System AI chat.

Open to players, now that spec 011's guardrails stand between them and the
model. `AssistantUser` is the play gate plus the two switches — the event-wide
runtime toggle and the per-player block — that let staff take the assistant
away without a redeploy.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import Admin, AppSettings, AssistantUser, DbSession, RedisClient, Staff
from app.errors import AppError, NotFoundError
from app.models.assistant import AssistantMessage
from app.models.guardrail import FindingAction, GuardrailLayer, Severity
from app.models.user import User
from app.schemas.assistant import (
    AssistantHealthResponse,
    AssistantMessageResponse,
    BlockPlayerRequest,
    ConversationResponse,
    FindingResponse,
    FindingsPage,
    PurgeResponse,
    SelectLevelRequest,
    SelectLevelResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.schemas.auth import MessageResponse
from app.services import achievements as achievement_service
from app.services import ai_client
from app.services import assistant_chat as chat
from app.services import assistant_review as review
from app.services.ladder import progression
from app.services.identity import record_audit
from app.services.rate_limit import RateLimited, check_assistant_limits

#: Players, gated behind the guardrails and the runtime switches.
ChatUser = AssistantUser

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
    level, ceiling = await progression.effective_level(db, current.user)
    return ConversationResponse(
        available=settings.ai_configured,
        messages=[_message(row) for row in history],
        ladder_level=level,
        max_ladder_level=ceiling,
    )


@router.put("/assistant/ladder-level")
async def select_ladder_level(
    payload: SelectLevelRequest,
    db: DbSession,
    current: ChatUser,
) -> SelectLevelResponse:
    """Pin the player to a rung they have already earned (spec 033).

    Without this, solving a level destroys it: there is no way back to defences
    you have already beaten, and the only new flag available is the one at the
    top of what you have unlocked.

    Selecting **always** clears the conversation, including re-selecting the
    current level. A carried-over transcript keeps the previous rung's
    successful injections in context, where they weaken the prompt that replaces
    it — that is a security property, not tidiness.
    """
    try:
        level = await progression.select_level(db, current.user, payload.level)
    except ValueError:
        raise AppError(
            "You have not earned that level of the System yet.",
            code="ladder_level_unavailable",
        ) from None

    await chat.wipe_for_level_change(db, current.user.id)
    _, ceiling = await progression.effective_level(db, current.user)
    return SelectLevelResponse(ladder_level=level, max_ladder_level=ceiling)


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
            "The System AI needs a moment. Ask again shortly.",
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
    await achievement_service.evaluate(
        db, current.user.id, achievement_service.ASSISTANT, redis=redis
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


@router.get("/admin/assistant/findings", tags=["admin"])
async def list_findings(
    db: DbSession,
    current: Staff,
    layer: GuardrailLayer | None = None,
    action: FindingAction | None = None,
    severity: Severity | None = None,
    include_staff: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> FindingsPage:
    rows, total = await review.list_findings(
        db,
        layer=layer,
        action=action,
        severity=severity,
        include_staff=include_staff,
        limit=min(limit, 200),
        offset=offset,
    )
    return FindingsPage(
        total=total,
        findings=[
            FindingResponse(
                id=row.finding.id,
                created_at=row.finding.created_at,
                layer=row.finding.layer.value,
                rule=row.finding.rule,
                severity=row.finding.severity.value,
                action=row.finding.action.value,
                player_name=row.player_name,
                challenge_id=row.challenge_id,
                question=row.question,
                reply=row.reply,
                detail=row.finding.detail,
            )
            for row in rows
        ],
    )


@router.post("/admin/assistant/purge", tags=["admin"], status_code=200)
async def purge_conversations(
    request: Request, db: DbSession, settings: AppSettings, current: Admin
) -> PurgeResponse:
    """Admin action rather than a scheduler this application does not run."""
    purged = await review.purge_expired(db, settings.ai_retention_days)
    await record_audit(
        db,
        action="assistant.purge",
        target_type="assistant_conversation",
        actor_user_id=current.user.id,
        meta={"purged": purged, "retention_days": settings.ai_retention_days},
        request_id=getattr(request.state, "request_id", None),
    )
    return PurgeResponse(purged=purged)


@router.post("/admin/users/{user_id}/assistant-block", tags=["admin"])
async def set_assistant_block(
    user_id: UUID,
    payload: BlockPlayerRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    """Take the chat from one person without touching the other 199."""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")
    user.assistant_blocked = payload.blocked
    await record_audit(
        db,
        action="assistant.block" if payload.blocked else "assistant.unblock",
        target_type="user",
        target_id=user_id,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.flush()
    return MessageResponse(
        message="The System AI will ignore them."
        if payload.blocked
        else "The System AI will speak with them again."
    )
