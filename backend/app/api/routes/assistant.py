"""The System AI chat.

Open to players, now that spec 011's guardrails stand between them and the
model. `AssistantUser` is the play gate plus the two switches — the event-wide
runtime toggle and the per-player block — that let staff take the assistant
away without a redeploy.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import (
    Admin,
    AppSettings,
    AssistantUser,
    DbSession,
    Player,
    RedisClient,
    Staff,
)
from app.errors import AppError, NotFoundError
from app.models.assistant import AssistantMessage
from app.models.guardrail import FindingAction, GuardrailLayer, Severity
from app.models.user import User
from app.schemas.assistant import (
    AcceptTermsRequest,
    AssistantHealthResponse,
    AssistantMessageResponse,
    BlockPlayerRequest,
    ConversationResponse,
    FindingResponse,
    FindingsPage,
    MetricsResponse,
    PurgeResponse,
    RungResponse,
    SelectLevelRequest,
    SelectLevelResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionResponse,
    SessionsPage,
    TermsResponse,
    TermsSummaryResponse,
    TranscriptResponse,
    TranscriptTurnResponse,
    WindowResponse,
)
from app.schemas.auth import MessageResponse
from app.services import achievements as achievement_service
from app.services import ai_client, assistant_terms
from app.services import assistant_chat as chat
from app.services import assistant_metrics as metrics
from app.services import assistant_review as review
from app.services.identity import record_audit
from app.services.ladder import progression
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


@router.get("/assistant/terms")
async def get_terms(db: DbSession, settings: AppSettings, current: Player) -> TermsResponse:
    """The terms, and whether this player has accepted them (spec 035).

    Gated on `Player`, not `AssistantUser` — the assistant gate is the thing
    that refuses them for *not* having accepted, so reading the terms through it
    would be a loop.
    """
    terms = assistant_terms.load(settings)
    return TermsResponse(
        text=terms.text,
        version=terms.version,
        accepted=await assistant_terms.has_accepted(db, current.user.id, terms.version),
    )


@router.post("/assistant/terms/accept")
async def accept_terms(
    payload: AcceptTermsRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> TermsResponse:
    """Record acceptance of the version the player was shown.

    The submitted version is checked against the current one. If the file
    changed between the page loading and the click, the acceptance is refused
    and the new text comes back — otherwise a player could accept wording they
    were never displayed, which is the one failure that would make the whole
    record worthless.
    """
    terms = assistant_terms.load(settings)
    if payload.version != terms.version:
        raise AppError(
            "These terms have been updated. Please read them again.",
            code="assistant_terms_stale",
            status_code=409,
        )

    await assistant_terms.accept(db, current.user.id, terms.version)
    await record_audit(
        db,
        action="assistant.terms_accepted",
        target_type="user",
        target_id=current.user.id,
        actor_user_id=current.user.id,
        meta={"version": terms.version},
        request_id=getattr(request.state, "request_id", None),
    )
    return TermsResponse(text=terms.text, version=terms.version, accepted=True)


@router.get("/admin/assistant/terms", tags=["admin"])
async def terms_summary(
    db: DbSession,
    settings: AppSettings,
    current: Staff,
    include_names: bool = False,
) -> TermsSummaryResponse:
    """Which version is live, and how many have accepted it."""
    terms = assistant_terms.load(settings)
    result = await assistant_terms.summary(db, terms.version, include_names=include_names)
    return TermsSummaryResponse(
        version=result.version,
        accepted=result.accepted,
        outstanding=result.outstanding,
        outstanding_names=result.outstanding_names,
    )


@router.get("/assistant/conversation")
async def get_conversation(
    db: DbSession, settings: AppSettings, current: ChatUser
) -> ConversationResponse:
    # Applying the level change on read, not on the next send (spec 036). A
    # "wipe" is now an integer increment rather than a delete, which is what
    # made doing it here unappealing before — and waiting meant a player who had
    # just levelled up saw the previous rung's turns, which are not what the
    # model would be given.
    level, ceiling = await progression.effective_level(db, current.user)
    await chat.reset_if_level_changed(db, current.user.id, level)

    history = await chat.history_for(db, current.user.id, settings.ai_history_turns * 2)
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
    rule: str | None = None,
    user_id: UUID | None = None,
    since: datetime | None = None,
    unreviewed: bool = False,
    include_staff: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> FindingsPage:
    rows, total = await review.list_findings(
        db,
        layer=layer,
        action=action,
        severity=severity,
        rule=rule,
        user_id=user_id,
        since=since,
        unreviewed=unreviewed,
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
                acknowledged_at=row.finding.acknowledged_at,
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


# --------------------------------------------------------------------------
# The admin console (spec 034)
# --------------------------------------------------------------------------


@router.get("/admin/assistant/metrics", tags=["admin"])
async def assistant_metrics_endpoint(
    db: DbSession, current: Staff, include_staff: bool = False
) -> MetricsResponse:
    """Aggregates for the health panel.

    Computed on read: at a few tens of thousands of message rows, a metrics
    pipeline for a three-day event would be building the wrong thing.
    """
    result = await metrics.collect(db, include_staff=include_staff)
    return MetricsResponse(
        generated_at=result.generated_at,
        windows={label: WindowResponse(**vars(window)) for label, window in result.windows.items()},
        errors_by_reason=result.errors_by_reason,
        findings_by_rule=result.findings_by_rule,
        rungs=[RungResponse(**vars(rung)) for rung in result.rungs],
        total_turns=result.total_turns,
        total_conversations=result.total_conversations,
        unacknowledged_findings=result.unacknowledged_findings,
    )


@router.post("/admin/assistant/findings/{finding_id}/acknowledge", tags=["admin"])
async def acknowledge_finding(finding_id: UUID, db: DbSession, current: Staff) -> MessageResponse:
    """Mark a finding as read.

    Acknowledged is not "wrong" or "actioned" — it means somebody looked. Without
    it, every refresh shows the same rows and a backlog cannot be worked through.
    """
    if not await review.acknowledge(db, finding_id, current.user.id):
        raise NotFoundError("No such finding.")
    return MessageResponse(message="Marked as seen.")


@router.get("/admin/assistant/sessions", tags=["admin"])
async def list_sessions(
    db: DbSession,
    current: Staff,
    minutes: int | None = 30,
    include_staff: bool = False,
    limit: int = 100,
) -> SessionsPage:
    """Who is talking to the System AI. **Metadata only.**

    ``minutes`` is what "open" means: there is no login-session concept here, so
    an open session is a recently active one. Pass nothing to widen it to the
    whole event.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes) if minutes else None
    rows = await review.list_sessions(
        db, since=since, include_staff=include_staff, limit=min(limit, 200)
    )
    return SessionsPage(
        sessions=[SessionResponse(**vars(row)) for row in rows],
        hidden_staff_findings=await review.hidden_staff_findings(db),
    )


@router.get("/admin/assistant/sessions/{user_id}", tags=["admin"])
async def read_transcript(
    user_id: UUID, request: Request, db: DbSession, current: Admin
) -> TranscriptResponse:
    """One player's conversation, in full.

    **Admin, not staff.** Spec 011 ruled a general transcript browser out; spec
    034 reverses that on the project owner's direction, because the assistant is
    now a challenge and debugging a broken rung needs the turns a filter did not
    catch. Players are told their conversation is readable (spec 035), which is
    what makes this sound.

    Opening one writes an audit row naming both people. Light on purpose — it
    exists so "who looked at this" has an answer, not to police anybody.
    """
    result = await review.transcript(db, user_id)
    if result is None:
        raise NotFoundError("No such user.")

    await record_audit(
        db,
        action="assistant.transcript_read",
        target_type="user",
        target_id=user_id,
        actor_user_id=current.user.id,
        meta={"turns": len(result.turns)},
        request_id=getattr(request.state, "request_id", None),
    )

    return TranscriptResponse(
        user_id=result.user_id,
        player_name=result.player_name,
        exists=result.exists,
        current_session=result.current_session,
        turns=[TranscriptTurnResponse(**vars(turn)) for turn in result.turns],
    )
