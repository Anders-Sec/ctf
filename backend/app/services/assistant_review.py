"""Reading and resolving guardrail findings.

The review surface is deliberately narrow: flagged exchanges and their immediate
context, not a general transcript browser. This is a work event and these are
colleagues; their chat logs are not staff entertainment. Spec 007 made the same
call for the same reason.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantMessage, MessageRole
from app.models.guardrail import AssistantFinding, FindingAction, GuardrailLayer, Severity
from app.models.user import User


@dataclass(frozen=True)
class FindingRow:
    finding: AssistantFinding
    player_name: str
    #: The player's message and the reply, so a reviewer sees the exchange
    #: rather than one half of it. `original_content` is preferred for the
    #: reply, because a deflected one is the whole point of looking.
    question: str | None
    reply: str | None
    challenge_id: UUID | None


async def list_findings(
    db: AsyncSession,
    *,
    layer: GuardrailLayer | None = None,
    action: FindingAction | None = None,
    severity: Severity | None = None,
    include_staff: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FindingRow], int]:
    """Newest first. Staff findings are hidden by default so our own testing
    does not bury the real ones."""
    conditions = []
    if layer is not None:
        conditions.append(AssistantFinding.layer == layer)
    if action is not None:
        conditions.append(AssistantFinding.action == action)
    if severity is not None:
        conditions.append(AssistantFinding.severity == severity)
    if not include_staff:
        conditions.append(AssistantFinding.from_staff.is_(False))

    total = (await db.scalar(select(func.count(AssistantFinding.id)).where(*conditions))) or 0

    findings = (
        (
            await db.execute(
                select(AssistantFinding)
                .where(*conditions)
                .order_by(AssistantFinding.created_at.desc(), AssistantFinding.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return [await _decorate(db, finding) for finding in findings], total


async def _decorate(db: AsyncSession, finding: AssistantFinding) -> FindingRow:
    player = await db.get(User, finding.user_id)
    question, reply, challenge_id = await _exchange(db, finding)
    return FindingRow(
        finding=finding,
        player_name=player.display_name if player else "(unknown)",
        question=question,
        reply=reply,
        challenge_id=challenge_id,
    )


async def _exchange(
    db: AsyncSession, finding: AssistantFinding
) -> tuple[str | None, str | None, UUID | None]:
    """The message the finding is attached to, and its neighbour in the thread.

    A finding survives retention (its `message_id` goes null), so both halves
    may already be gone — the finding is still the record of what happened.
    """
    if finding.message_id is None:
        return None, None, None

    message = await db.get(AssistantMessage, finding.message_id)
    if message is None:
        return None, None, None

    partner = await _partner(db, message)
    if message.role == MessageRole.USER:
        question, answer = message, partner
    else:
        question, answer = partner, message

    reply_text = None
    if answer is not None:
        # The suppressed text is the point of the review; fall back to what the
        # player saw only when nothing was withheld.
        reply_text = answer.original_content or answer.content

    return (
        question.content if question else None,
        reply_text,
        message.challenge_id,
    )


async def _partner(db: AsyncSession, message: AssistantMessage) -> AssistantMessage | None:
    """The other half of the turn: the reply to a question, or its question."""
    offset = 1 if message.role == MessageRole.USER else -1
    return (
        await db.execute(
            select(AssistantMessage).where(
                AssistantMessage.conversation_id == message.conversation_id,
                AssistantMessage.sequence == message.sequence + offset,
            )
        )
    ).scalar_one_or_none()


async def purge_expired(db: AsyncSession, retention_days: int, now: datetime | None = None) -> int:
    """Delete conversations older than the retention window.

    Findings are **not** purged with them — they are the record of what happened
    and never contain answer values or reply text. The message FK nulls itself.

    Run as an admin action and once at startup rather than on a scheduler this
    application does not have: for an event that lasts days, a button somebody
    presses beats a cron nobody notices failing.
    """
    from sqlalchemy import delete

    from app.models.assistant import AssistantConversation

    now = now or datetime.now(UTC)
    cutoff_dt = datetime.fromtimestamp(now.timestamp() - retention_days * 86400, tz=UTC)

    # A bulk delete rather than ORM deletes: the messages cascade at the database
    # level (`ON DELETE CASCADE`), and the ORM path would first try to load the
    # `lazy="raise"` messages collection to cascade it and raise instead.
    result = await db.execute(
        delete(AssistantConversation).where(
            AssistantConversation.last_message_at.is_not(None),
            AssistantConversation.last_message_at < cutoff_dt,
        )
    )
    await db.flush()
    return result.rowcount or 0
