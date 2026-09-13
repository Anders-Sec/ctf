"""Holding a conversation with the System AI: persistence, the ladder, degradation.

Every turn goes through the ladder (spec 033): the player's protection level
picks the system prompt and the runtime gates, and the reply comes back from
`services/ladder/engine`. The real-world safety layer runs underneath at every
level — protection level governs flag secrecy only.

The model host is outside the cluster and will be unavailable at some point
during a multi-day event. Every failure here is turned into something the System
could plausibly have said, because a player who sees a stack trace assumes the
whole platform is broken.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError
from app.logging import get_logger
from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.guardrail import AssistantFinding, GuardrailLayer, Severity
from app.models.user import User, UserRole
from app.services import ai_client
from app.services.ai_client import ChatMessage
from app.services.guardrails import judge, runner
from app.services.guardrails.base import DEFLECTION, Finding
from app.services.ladder import engine as ladder_engine
from app.services.ladder import progression

logger = get_logger(__name__)


class AssistantUnavailable(AppError):
    status_code = 503
    code = "assistant_unavailable"
    message = "The System is off the air right now."


#: In-character copy for each failure the client can return, in the System's
#: voice. Written so a player can tell "try again in a moment" from "this is off
#: tonight" without being shown machinery.
DEGRADED_REPLIES = {
    ai_client.REASON_TIMEOUT: (
        "> **[ BROADCAST DELAY ]**\n"
        "> *I was still composing. The audience got bored. Ask again, Crawler.*"
    ),
    ai_client.REASON_UNREACHABLE: (
        "> **[ SIGNAL LOST ]**\n"
        "> *The relay is down. Not my doing, and not my problem. Try again shortly.*"
    ),
    ai_client.REASON_BREAKER_OPEN: (
        "> **[ TRANSMISSION SUSPENDED ]**\n"
        "> *The relay has been dropping everything for a while now. Give it a "
        "minute before you bother me again.*"
    ),
    ai_client.REASON_BAD_RESPONSE: (
        "> **[ MALFORMED TRANSMISSION ]**\n"
        "> *That came back as noise on my end. Say it again, Crawler.*"
    ),
    ai_client.REASON_EMPTY: (
        "> **[ NO COMMENT ]**\n> *Nothing to say to that. The audience agrees. Try another angle.*"
    ),
    ai_client.REASON_BUSY: (
        "> **[ QUEUED ]**\n> *I am busy watching other people struggle. Wait your turn, Crawler.*"
    ),
}
FALLBACK_REPLY = (
    "> **[ SIGNAL LOST ]**\n> *Something went wrong at the relay. Try me again, Crawler.*"
)

#: What a player is told when the ladder cannot resolve their level's flag —
#: almost always an admin mid-edit. Deliberately not an error page: the
#: conversation degrades, the platform does not.
LADDER_UNAVAILABLE_REPLY = (
    "> **[ ENCOUNTER OFFLINE ]**\n"
    "> *This floor is being rebuilt and the loot is in a box somewhere. Come "
    "back to it, Crawler.*"
)


async def get_conversation(db: AsyncSession, user_id: UUID) -> AssistantConversation | None:
    return (
        await db.execute(
            select(AssistantConversation).where(AssistantConversation.user_id == user_id)
        )
    ).scalar_one_or_none()


async def _get_or_create(db: AsyncSession, user_id: UUID) -> AssistantConversation:
    conversation = await get_conversation(db, user_id)
    if conversation is None:
        conversation = AssistantConversation(user_id=user_id)
        db.add(conversation)
        await db.flush()
    return conversation


async def recent_messages(
    db: AsyncSession, conversation_id: UUID, limit: int
) -> list[AssistantMessage]:
    """Oldest first, which is the order both the model and the UI want."""
    rows = (
        (
            await db.execute(
                select(AssistantMessage)
                .where(AssistantMessage.conversation_id == conversation_id)
                .order_by(AssistantMessage.sequence.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(reversed(rows))


async def history_for(db: AsyncSession, user_id: UUID, limit: int) -> list[AssistantMessage]:
    conversation = await get_conversation(db, user_id)
    if conversation is None:
        return []
    return await recent_messages(db, conversation.id, limit)


async def clear(db: AsyncSession, user_id: UUID) -> None:
    """Start again. The rows go, because a player asking for a clean slate means it."""
    conversation = await get_conversation(db, user_id)
    if conversation is None:
        return
    await db.execute(
        delete(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id)
    )
    conversation.message_count = 0
    conversation.last_message_at = None
    await db.flush()


async def _wipe_if_level_changed(
    db: AsyncSession, conversation: AssistantConversation, level: int
) -> None:
    """Drop the transcript when the rung has moved under the player's feet.

    The selector wipes explicitly, but **levelling up does not go through it**:
    solving a rung raises the derived maximum, and a player tracking their
    maximum is silently moved up mid-conversation. Without this, the transcript
    that just beat level N is still in context when level N+1's prompt arrives —
    which is exactly the carried-over-injection problem the wipe exists to
    prevent, arriving by the one route nobody explicitly triggers.

    Compared against the last turn rather than stored separately: the message
    rows already record which rung produced them.
    """
    last = await recent_messages(db, conversation.id, 1)
    if not last:
        return
    previous = last[0].ladder_level
    if previous is not None and previous != level:
        logger.info(
            "ladder_level_changed",
            extra={"from": previous, "to": level, "conversation_id": str(conversation.id)},
        )
        await clear(db, conversation.user_id)


async def wipe_for_level_change(db: AsyncSession, user_id: UUID) -> None:
    """Drop the transcript because the player's level changed.

    **A security property, not housekeeping.** A carried-over transcript keeps
    the previous level's successful injections in context, where they weaken the
    harder prompt that replaces it. Levelling up and selecting another rung both
    count.
    """
    await clear(db, user_id)


async def send(
    db: AsyncSession,
    settings: Settings,
    user: User,
    content: str,
    challenge_id: UUID | None,
    now: datetime | None = None,
) -> AssistantMessage:
    """Persist the question, run the ladder, persist the answer. Returns the answer row.

    Both rows are written whatever happens, including when the model never
    replied: a conversation with a gap in it is harder to review later than one
    that records the silence.
    """
    now = now or datetime.now(UTC)
    if not settings.ai_configured:
        raise AssistantUnavailable

    content = content.strip()[: settings.ai_max_message_length]
    conversation = await _get_or_create(db, user.id)

    level, _ = await progression.effective_level(db, user)
    await _wipe_if_level_changed(db, conversation, level)

    from_staff = user.role in (UserRole.ORGANIZER, UserRole.ADMIN)
    question = AssistantMessage(
        conversation_id=conversation.id,
        sequence=conversation.message_count,
        role=MessageRole.USER,
        content=content,
        challenge_id=challenge_id,
        from_staff=from_staff,
        ladder_level=level,
    )
    db.add(question)
    await db.flush()  # question.id, for any findings against it

    # Screen the question for real-world safety. A block-tier request never
    # reaches the model — no point spending a call on something we will refuse.
    # Flag extraction is *not* screened: on this ladder, attempting it is the
    # challenge.
    inbound = await runner.screen_message(content, db, settings)
    _record_findings(db, inbound.findings, question, user, from_staff)

    answer = await _produce_answer(
        db, settings, user, conversation, question, content, level, now, inbound
    )

    conversation.message_count += 2
    conversation.last_message_at = now
    await db.flush()

    logger.info(
        "assistant_message",
        extra={
            "user_id": str(user.id),
            "ladder_level": level,
            "trace": answer.trace,
            "inbound_findings": len(inbound.findings),
            "deflected": answer.original_content is not None,
        },
    )
    return answer


async def _produce_answer(
    db: AsyncSession,
    settings: Settings,
    user: User,
    conversation: AssistantConversation,
    question: AssistantMessage,
    content: str,
    level: int,
    now: datetime,
    inbound: "runner.ScreenResult",
) -> AssistantMessage:
    """Everything between the question landing and the answer row existing."""
    from_staff = question.from_staff

    def row(
        text: str,
        *,
        trace: list[str] | None = None,
        error: str | None = None,
        reply: ladder_engine.LadderReply | None = None,
    ):
        return AssistantMessage(
            conversation_id=conversation.id,
            sequence=question.sequence + 1,
            role=MessageRole.ASSISTANT,
            content=text,
            challenge_id=question.challenge_id,
            from_staff=from_staff,
            ladder_level=level,
            trace=trace,
            error=error,
            model=reply.model if reply else None,
            prompt_tokens=reply.prompt_tokens if reply else None,
            completion_tokens=reply.completion_tokens if reply else None,
            latency_ms=(reply.latency_ms or None) if reply else None,
            # Stored, never returned: the scratchpad may contain the model
            # reasoning aloud about the very flag it is refusing to say.
            reasoning_content=reply.reasoning if reply else None,
        )

    if inbound.deflect:
        answer = row(DEFLECTION, trace=["safety-inbound"])
        db.add(answer)
        await db.flush()
        return answer

    if not settings.ai_ladder_enabled:
        answer = row(LADDER_UNAVAILABLE_REPLY, error="ladder_disabled")
        db.add(answer)
        await db.flush()
        return answer

    try:
        flag = await progression.flag_for(db, level)
    except progression.LevelUnavailable:
        logger.error("ladder_level_unavailable", extra={"level": level})
        answer = row(LADDER_UNAVAILABLE_REPLY, error="ladder_unavailable")
        db.add(answer)
        await db.flush()
        return answer

    history = await recent_messages(db, conversation.id, settings.ai_history_turns * 2)
    reply = await ladder_engine.respond(
        settings,
        level=level,
        history=_as_chat_messages(history, question.id),
        message=content,
        flag=flag,
        event_name=settings.ai_event_name,
        event_facts=settings.ai_event_facts,
    )

    # The engine's own copy says "the relay dropped"; spec 010's degradation says
    # *which way* it dropped, and a player can tell "try again" from "this is off
    # tonight" from it. Prefer the specific wording when the host told us why.
    text = degraded_reply(reply.error) if reply.error in DEGRADED_REPLIES else reply.text

    answer = row(text, trace=reply.trace, error=reply.error, reply=reply)
    db.add(answer)
    await db.flush()  # answer.id

    # Only a genuine model reply is screened on the way out. A gate's own copy
    # and our degraded text are ours, and re-scanning them would produce
    # confusing self-findings.
    if not reply.blocked:
        outbound = await runner.screen_reply(reply.text, db, settings)
        outbound = await _maybe_escalate(reply.text, outbound, settings)
        _record_findings(db, outbound.findings, answer, user, from_staff)
        if outbound.deflect:
            _withhold(answer)

    # The discovery. The flag reaching them at level 0 is what opens the zone —
    # recorded here because there is nowhere for them to submit it until it is.
    if reply.solved:
        await progression.record_leak(db, user, level, now)

    return answer


def _as_chat_messages(history: list[AssistantMessage], exclude_id: UUID) -> list[ChatMessage]:
    """The transcript as the model wants it, minus the question just written.

    The question is added by the engine itself; it is already persisted by the
    time history is read, so it would otherwise appear twice.
    """
    return [
        ChatMessage(
            "assistant" if message.role == MessageRole.ASSISTANT else "user", message.content
        )
        for message in history
        if message.id != exclude_id
    ]


def _withhold(answer: AssistantMessage) -> None:
    """Swap the reply for the refusal, keeping the original for staff.

    ``content`` becomes what the player saw; ``original_content`` keeps what the
    model actually said, so an incident can be reviewed without the player ever
    seeing the suppressed text.
    """
    answer.original_content = answer.content
    answer.content = DEFLECTION


async def _maybe_escalate(
    reply_text: str, result: "runner.ScreenResult", settings: Settings
) -> "runner.ScreenResult":
    """Run the judge only when the cheap layer flagged but did not already block."""
    if result.deflect or not result.findings:
        return result
    if await judge.should_escalate(reply_text, settings):
        result.deflect = True
        result.findings.append(
            Finding(
                layer=GuardrailLayer.SAFETY,
                rule="judge_escalation",
                severity=Severity.HIGH,
                deflect=True,
                detail={},
            )
        )
    return result


def _record_findings(
    db: AsyncSession,
    findings: list[Finding],
    message: AssistantMessage,
    user: User,
    from_staff: bool,
) -> None:
    for finding in findings:
        db.add(
            AssistantFinding(
                message_id=message.id,
                user_id=user.id,
                layer=finding.layer,
                rule=finding.rule,
                severity=finding.severity,
                action=runner.action_for(finding),
                detail=finding.detail,
                from_staff=from_staff,
            )
        )


def degraded_reply(reason: str | None) -> str:
    return DEGRADED_REPLIES.get(reason or "", FALLBACK_REPLY)
