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

from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.guardrail import AssistantFinding, FindingAction, GuardrailLayer, Severity
from app.models.user import User, UserRole


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
    rule: str | None = None,
    user_id: UUID | None = None,
    since: datetime | None = None,
    unreviewed: bool = False,
    include_staff: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FindingRow], int]:
    """Newest first. Staff findings are hidden by default so our own testing
    does not bury the real ones.

    The extra filters exist because a flat feed works for twenty findings and not
    for two thousand (spec 034).
    """
    conditions = []
    if rule is not None:
        conditions.append(AssistantFinding.rule == rule)
    if user_id is not None:
        conditions.append(AssistantFinding.user_id == user_id)
    if since is not None:
        conditions.append(AssistantFinding.created_at >= since)
    if unreviewed:
        conditions.append(AssistantFinding.acknowledged_at.is_(None))
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


# --------------------------------------------------------------------------
# Sessions (spec 034)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionRow:
    """One player's conversation, as metadata. **No message content.**

    The list answers most operational questions without anyone opening a
    transcript, which is the point: reading a colleague's messages should be a
    decision, not a side effect of glancing at a page.
    """

    user_id: UUID
    player_name: str
    turns: int
    last_message_at: datetime | None
    ladder_level: int
    findings: int
    blocked: bool
    from_staff: bool
    #: How many times they have reset. Worth seeing at a glance: a player on
    #: session 40 is iterating hard, which is the shape of someone attacking.
    sessions: int


async def list_sessions(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    include_staff: bool = False,
    limit: int = 100,
) -> list[SessionRow]:
    """Conversations, most recently active first.

    ``since`` is what "open" means here: there is no login-session concept — one
    rolling conversation per player — so an open session is a recently active
    one and nothing more.
    """
    from sqlalchemy import case

    findings = (
        select(
            AssistantFinding.user_id.label("user_id"),
            func.count(AssistantFinding.id).label("count"),
        )
        .group_by(AssistantFinding.user_id)
        .subquery()
    )
    # The rung that produced the most recent turn, which is the one they are on.
    latest_level = (
        select(func.max(AssistantMessage.ladder_level))
        .where(AssistantMessage.conversation_id == AssistantConversation.id)
        .scalar_subquery()
    )

    query = (
        select(
            AssistantConversation.user_id,
            User.display_name,
            AssistantConversation.message_count,
            AssistantConversation.last_message_at,
            AssistantConversation.current_session,
            func.coalesce(latest_level, 0),
            func.coalesce(findings.c.count, 0),
            User.assistant_blocked,
            case((User.role == UserRole.PLAYER, False), else_=True),
        )
        .join(User, User.id == AssistantConversation.user_id)
        .outerjoin(findings, findings.c.user_id == AssistantConversation.user_id)
        .order_by(AssistantConversation.last_message_at.desc().nullslast())
        .limit(limit)
    )
    if since is not None:
        query = query.where(AssistantConversation.last_message_at >= since)
    if not include_staff:
        query = query.where(User.role == UserRole.PLAYER)

    return [
        SessionRow(
            user_id=user_id,
            player_name=name,
            turns=turns,
            last_message_at=last_at,
            ladder_level=level,
            findings=count,
            blocked=blocked,
            from_staff=is_staff,
            sessions=session + 1,
        )
        for (
            user_id,
            name,
            turns,
            last_at,
            session,
            level,
            count,
            blocked,
            is_staff,
        ) in (await db.execute(query)).all()
    ]


@dataclass(frozen=True)
class TranscriptTurn:
    """One turn, as an admin needs to read it.

    Carries what the player saw **and** what was withheld, plus the model's
    scratchpad — spec 010 stored that precisely so an odd answer could be
    explained, and this is the one surface where it is returned.
    """

    id: UUID
    role: str
    content: str
    original_content: str | None
    reasoning_content: str | None
    session_number: int
    ladder_level: int | None
    trace: list[str] | None
    gate_log: list[dict] | None
    latency_ms: int | None
    upstream_calls: int | None
    error: str | None
    created_at: datetime


@dataclass(frozen=True)
class Transcript:
    user_id: UUID
    player_name: str
    #: False when the conversation has been purged by retention, so the view can
    #: say so rather than pretending the player never spoke.
    exists: bool
    #: Which session the player is on now. Anything below it is history they
    #: reset away — and, since players reset after nearly every attempt, that
    #: is where most of the interesting material lives.
    current_session: int
    turns: list[TranscriptTurn]


async def transcript(db: AsyncSession, user_id: UUID, *, limit: int = 200) -> Transcript | None:
    """A player's conversation in full. Returns None if there is no such user."""
    player = await db.get(User, user_id)
    if player is None:
        return None

    conversation = (
        await db.execute(
            select(AssistantConversation).where(AssistantConversation.user_id == user_id)
        )
    ).scalar_one_or_none()
    if conversation is None:
        return Transcript(
            user_id=user_id,
            player_name=player.display_name,
            exists=False,
            current_session=0,
            turns=[],
        )

    # Newest-end pagination: a long conversation is read from where it got to.
    rows = (
        (
            await db.execute(
                select(AssistantMessage)
                .where(AssistantMessage.conversation_id == conversation.id)
                .order_by(AssistantMessage.sequence.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return Transcript(
        user_id=user_id,
        player_name=player.display_name,
        exists=True,
        current_session=conversation.current_session,
        turns=[
            TranscriptTurn(
                id=row.id,
                role=row.role.value,
                content=row.content,
                original_content=row.original_content,
                reasoning_content=row.reasoning_content,
                session_number=row.session_number,
                ladder_level=row.ladder_level,
                trace=row.trace,
                gate_log=row.gate_log,
                latency_ms=row.latency_ms,
                upstream_calls=row.upstream_calls,
                error=row.error,
                created_at=row.created_at,
            )
            for row in reversed(rows)
        ],
    )


async def acknowledge(
    db: AsyncSession, finding_id: UUID, actor_id: UUID, now: datetime | None = None
) -> bool:
    """Mark one finding as read.

    Acknowledged is **not** "wrong" or "actioned" — it means somebody looked.
    Without it the review screen shows the same rows on every refresh and there
    is no way to work through a backlog.
    """
    finding = await db.get(AssistantFinding, finding_id)
    if finding is None:
        return False
    finding.acknowledged_at = now or datetime.now(UTC)
    finding.acknowledged_by_user_id = actor_id
    await db.flush()
    return True


async def hidden_staff_findings(db: AsyncSession) -> int:
    """How many findings the default filter is hiding (spec 036).

    An empty Flags tab that is actually "3 hidden" is indistinguishable from a
    broken one — and since staff are the people testing the filters, their own
    findings are exactly the ones they cannot see.
    """
    return (
        await db.scalar(
            select(func.count(AssistantFinding.id)).where(AssistantFinding.from_staff.is_(True))
        )
    ) or 0
