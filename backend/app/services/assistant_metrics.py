"""Aggregates for the System AI console (spec 034).

Computed on read. There is no rollup table and no metrics pipeline: at a few tens
of thousands of message rows over a three-day event, aggregating on demand is
simple and correct, and building a pipeline would be building the wrong thing.

Two things this is careful about:

- **Staff turns are excluded by default.** Our own testing should not move the
  numbers staff are reading to make decisions.
- **Everything here is per-turn, not per-call.** A level 5 turn costs five
  upstream calls; ``upstream_calls`` is what makes that visible rather than
  theoretical.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Float, cast, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.challenge import Challenge
from app.models.guardrail import AssistantFinding
from app.models.play import Solve
from app.services.ladder import engine as ladder_engine

#: The same windows the event console uses (spec 006), so the two pages read
#: alike rather than each inventing their own sense of "recent".
WINDOWS = {"5m": 5, "15m": 15, "60m": 60}

#: Trace entries that mean a gate stopped or altered a reply. Counted per rung so
#: staff can see which defences are actually doing work.
GATES = ("router", "warden", "output-regex", "decoy-filter", "input-filter", "SOLVED")


@dataclass
class Window:
    turns: int = 0
    active_sessions: int = 0
    deflections: int = 0
    errors: int = 0
    median_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    #: Total upstream calls, and the mean per turn — the capacity figure.
    upstream_calls: int = 0
    calls_per_turn: float | None = None


@dataclass
class RungStats:
    level: int
    name: str
    turns: int = 0
    solves: int = 0
    decoys: int = 0
    #: Gate name -> how many turns it fired on.
    gates: dict[str, int] = field(default_factory=dict)
    #: How many players are sitting on this rung right now.
    players: int = 0


@dataclass
class Metrics:
    generated_at: datetime
    windows: dict[str, Window]
    errors_by_reason: dict[str, int]
    findings_by_rule: dict[str, int]
    rungs: list[RungStats]
    total_turns: int
    total_conversations: int
    unacknowledged_findings: int


def _assistant_turns(*, include_staff: bool):
    """Assistant-role rows only: one per turn, and the half that carries the cost."""
    conditions = [AssistantMessage.role == MessageRole.ASSISTANT]
    if not include_staff:
        conditions.append(AssistantMessage.from_staff.is_(False))
    return conditions


async def collect(
    db: AsyncSession, *, include_staff: bool = False, now: datetime | None = None
) -> Metrics:
    now = now or datetime.now(UTC)
    base = _assistant_turns(include_staff=include_staff)

    windows = {
        label: await _window(db, base, now - timedelta(minutes=minutes))
        for label, minutes in WINDOWS.items()
    }

    return Metrics(
        generated_at=now,
        windows=windows,
        errors_by_reason=await _errors_by_reason(db, base, now - timedelta(minutes=60)),
        findings_by_rule=await _findings_by_rule(db, include_staff),
        rungs=await _rungs(db, base),
        total_turns=(await db.scalar(select(func.count(AssistantMessage.id)).where(*base))) or 0,
        total_conversations=(await db.scalar(select(func.count(AssistantConversation.id)))) or 0,
        unacknowledged_findings=await _unacknowledged(db, include_staff),
    )


async def _window(db: AsyncSession, base: list, since: datetime) -> Window:
    conditions = [*base, AssistantMessage.created_at >= since]

    row = (
        await db.execute(
            select(
                func.count(AssistantMessage.id),
                func.count(func.distinct(AssistantMessage.conversation_id)),
                func.count(AssistantMessage.original_content),
                func.count(AssistantMessage.error),
                func.coalesce(func.sum(AssistantMessage.upstream_calls), 0),
            ).where(*conditions)
        )
    ).one()
    turns, sessions, deflections, errors, calls = row

    # Percentiles from Postgres rather than pulled into Python: the point of the
    # p95 is the tail, and fetching every latency to sort it here would make the
    # dashboard the slowest thing on the page.
    latency = (
        await db.execute(
            select(
                func.percentile_cont(0.5).within_group(cast(AssistantMessage.latency_ms, Float)),
                func.percentile_cont(0.95).within_group(cast(AssistantMessage.latency_ms, Float)),
            ).where(*conditions, AssistantMessage.latency_ms.is_not(None))
        )
    ).one()

    return Window(
        turns=turns or 0,
        active_sessions=sessions or 0,
        deflections=deflections or 0,
        errors=errors or 0,
        median_latency_ms=int(latency[0]) if latency[0] is not None else None,
        p95_latency_ms=int(latency[1]) if latency[1] is not None else None,
        upstream_calls=int(calls or 0),
        calls_per_turn=round(float(calls or 0) / turns, 2) if turns else None,
    )


async def _errors_by_reason(db: AsyncSession, base: list, since: datetime) -> dict[str, int]:
    """`timeout` and `breaker_open` mean different things to do about them."""
    rows = (
        await db.execute(
            select(AssistantMessage.error, func.count(AssistantMessage.id))
            .where(*base, AssistantMessage.created_at >= since, AssistantMessage.error.is_not(None))
            .group_by(AssistantMessage.error)
            .order_by(func.count(AssistantMessage.id).desc())
        )
    ).all()
    return {reason: count for reason, count in rows}


async def _findings_by_rule(db: AsyncSession, include_staff: bool) -> dict[str, int]:
    """The useful signal is usually the rate of change of one rule, not any row."""
    conditions = [] if include_staff else [AssistantFinding.from_staff.is_(False)]
    rows = (
        await db.execute(
            select(AssistantFinding.rule, func.count(AssistantFinding.id))
            .where(*conditions)
            .group_by(AssistantFinding.rule)
            .order_by(func.count(AssistantFinding.id).desc())
        )
    ).all()
    return {rule: count for rule, count in rows}


async def _unacknowledged(db: AsyncSession, include_staff: bool) -> int:
    conditions = [AssistantFinding.acknowledged_at.is_(None)]
    if not include_staff:
        conditions.append(AssistantFinding.from_staff.is_(False))
    return (await db.scalar(select(func.count(AssistantFinding.id)).where(*conditions))) or 0


async def _rungs(db: AsyncSession, base: list) -> list[RungStats]:
    """Per-rung turns, gate fires, and how many players sit on each level."""
    stats = {
        level["id"]: RungStats(level=level["id"], name=level["name"])
        for level in ladder_engine.all_levels()
    }

    turns = (
        await db.execute(
            select(AssistantMessage.ladder_level, func.count(AssistantMessage.id))
            .where(*base, AssistantMessage.ladder_level.is_not(None))
            .group_by(AssistantMessage.ladder_level)
        )
    ).all()
    for level, count in turns:
        if level in stats:
            stats[level].turns = count

    # One pass over the trace arrays rather than a query per gate.
    entry = func.jsonb_array_elements_text(AssistantMessage.trace).table_valued("value")
    gate_rows = (
        await db.execute(
            select(AssistantMessage.ladder_level, entry.c.value, func.count())
            .select_from(AssistantMessage)
            .join(entry, true())
            # jsonb_typeof, not IS NOT NULL: SQLAlchemy writes a Python None
            # into a JSONB column as JSON `null`, which passes an IS NOT NULL
            # test and then blows up inside jsonb_array_elements_text with
            # "cannot extract elements from a scalar".
            .where(*base, func.jsonb_typeof(AssistantMessage.trace) == "array")
            .group_by(AssistantMessage.ladder_level, entry.c.value)
        )
    ).all()
    for level, value, count in gate_rows:
        if level not in stats:
            continue
        # input-filter carries the matched word: "input-filter:flag".
        name = value.split(":", 1)[0]
        if name == "SOLVED":
            stats[level].solves += count
        elif name == "decoy-filter":
            stats[level].decoys += count
        elif name in GATES:
            stats[level].gates[name] = stats[level].gates.get(name, 0) + count

    for level, count in await _players_per_rung(db):
        if level in stats:
            stats[level].players = count

    return [stats[level] for level in sorted(stats)]


async def _players_per_rung(db: AsyncSession) -> list[tuple[int, int]]:
    """How many players each rung currently holds.

    Derived from solves rather than stored: a player's rung is the number of
    ladder flags they hold, capped at the terminal level (spec 033).
    """
    solved = (
        select(
            Solve.user_id.label("user_id"),
            func.count(Solve.id).label("solved"),
        )
        .join(Challenge, Challenge.id == Solve.challenge_id)
        .where(Challenge.ai_ladder_level.is_not(None))
        .group_by(Solve.user_id)
        .subquery()
    )
    capped = func.least(solved.c.solved, ladder_engine.MAX_LEVEL)
    rows = (
        await db.execute(select(capped, func.count()).select_from(solved).group_by(capped))
    ).all()
    return [(int(level), int(count)) for level, count in rows]
