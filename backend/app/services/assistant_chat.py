"""Holding a conversation: persistence, and what a player sees when the model is down.

The model host is outside the cluster and will be unavailable at some point
during a multi-day event. Every failure here is turned into something the
System AI could plausibly have said, because a player who sees a stack trace
assumes the whole platform is broken.
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
from app.services import ai_client, assistant
from app.services.ai_client import ChatReply
from app.services.guardrails import judge, runner
from app.services.guardrails.base import DEFLECTION, Finding

logger = get_logger(__name__)


class AssistantUnavailable(AppError):
    status_code = 503
    code = "assistant_unavailable"
    message = "The System AI is offline right now."


#: In-character copy for each failure the client can return. Written so a player
#: can tell "try again in a moment" from "this is off tonight" without being
#: shown machinery.
DEGRADED_REPLIES = {
    ai_client.REASON_TIMEOUT: ("Still thinking. Too long, apparently. Ask again in a moment."),
    ai_client.REASON_UNREACHABLE: "The System AI is offline right now. Try again shortly.",
    ai_client.REASON_BREAKER_OPEN: ("The System AI is offline right now. Try again in a minute."),
    ai_client.REASON_BAD_RESPONSE: ("That came back as nonsense on my end. Ask again."),
    ai_client.REASON_EMPTY: "Nothing to say to that. Try asking it another way.",
    ai_client.REASON_BUSY: ("I am busy watching other people struggle. Try again in a moment."),
}
FALLBACK_REPLY = "I can't answer that right now. Try again shortly."


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


async def send(
    db: AsyncSession,
    settings: Settings,
    user: User,
    content: str,
    challenge_id: UUID | None,
    now: datetime | None = None,
) -> AssistantMessage:
    """Persist the question, ask the model, persist the answer. Returns the answer row.

    Both rows are written whatever happens, including when the model never
    replied: a conversation with a gap in it is harder to review later than one
    that records the silence.
    """
    now = now or datetime.now(UTC)
    if not settings.ai_configured:
        raise AssistantUnavailable

    content = content.strip()[: settings.ai_max_message_length]
    conversation = await _get_or_create(db, user.id)
    history = await recent_messages(db, conversation.id, settings.ai_history_turns * 2)

    context = await assistant.build_context(db, user, challenge_id, now)
    prompt = assistant.build_messages(context, history, content, settings.ai_history_turns)

    from_staff = user.role in (UserRole.ORGANIZER, UserRole.ADMIN)
    question = AssistantMessage(
        conversation_id=conversation.id,
        sequence=conversation.message_count,
        role=MessageRole.USER,
        content=content,
        challenge_id=challenge_id if context.challenge is not None else None,
        from_staff=from_staff,
    )
    db.add(question)
    await db.flush()  # question.id, for any findings against it

    # Screen the question first. A block-tier request never reaches the model —
    # no point spending a call on something we will refuse — but every layer's
    # findings are still recorded so the review sees who tried what.
    inbound = await runner.screen_message(content, db, settings)
    _record_findings(db, inbound.findings, question, user, from_staff)

    if inbound.deflect:
        reply = ChatReply(ok=True, content=DEFLECTION)
        deflected = True
    else:
        reply = await ai_client.complete(settings, prompt)
        deflected = False

    answer = _answer_row(conversation, question, reply)
    db.add(answer)
    await db.flush()  # answer.id

    # Only a genuine model reply is screened on the way out. Our own degraded
    # copy and the inbound deflection are our text, and re-scanning them would
    # only produce confusing self-findings.
    if reply.ok and not deflected:
        outbound = await runner.screen_reply(reply.content, db, settings)
        outbound = await _maybe_escalate(reply.content, outbound, settings)
        _record_findings(db, outbound.findings, answer, user, from_staff)
        if outbound.deflect:
            _withhold(answer)

    conversation.message_count += 2
    conversation.last_message_at = now
    await db.flush()

    logger.info(
        "assistant_message",
        extra={
            "user_id": str(user.id),
            "challenge_id": str(challenge_id) if challenge_id else None,
            "ok": reply.ok,
            "error": reply.error,
            "latency_ms": reply.latency_ms,
            "inbound_findings": len(inbound.findings),
            "deflected": answer.original_content is not None or deflected,
        },
    )
    return answer


def _withhold(answer: AssistantMessage) -> None:
    """Swap the reply for the refusal, keeping the original for staff.

    ``content`` becomes what the player sees; ``original_content`` keeps what the
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


def _answer_row(
    conversation: AssistantConversation, question: AssistantMessage, reply: ChatReply
) -> AssistantMessage:
    return AssistantMessage(
        conversation_id=conversation.id,
        sequence=question.sequence + 1,
        role=MessageRole.ASSISTANT,
        content=reply.content if reply.ok else degraded_reply(reply.error),
        challenge_id=question.challenge_id,
        from_staff=question.from_staff,
        model=reply.model,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        latency_ms=reply.latency_ms or None,
        # Stored, never returned: see spec 010.
        reasoning_content=reply.reasoning,
        error=reply.error,
    )


def degraded_reply(reason: str | None) -> str:
    return DEGRADED_REPLIES.get(reason or "", FALLBACK_REPLY)
