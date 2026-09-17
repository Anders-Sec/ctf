"""Operational admin actions: score overrides, reports, and the dashboard."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, ConflictError, NotFoundError
from app.logging import get_logger
from app.models.challenge import Challenge, ChallengeAnswer, ChallengeState
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.instance import ChallengeInstance, InstanceStatus
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.report import ChallengeReport, ReportStatus
from app.models.team import Team
from app.models.user import User, UserStatus
from app.services import signals
from app.services.identity import record_audit

logger = get_logger(__name__)

#: Below this, an attempt count says nothing — three wrong guesses on a hard
#: challenge is a Tuesday, not a broken answer rule.
HEALTH_ATTEMPT_FLOOR = 15


class InvalidAdjustment(AppError):
    status_code = 422
    code = "invalid_adjustment"
    message = "An adjustment must target exactly one player or one party."


@dataclass(frozen=True)
class ChallengeHealth:
    challenge_id: UUID
    title: str
    state: ChallengeState
    solve_count: int
    attempt_count: int
    open_reports: int
    #: True when many have tried and nobody has succeeded. The single most
    #: useful thing this dashboard reports.
    suspected_broken: bool
    #: True when nearly every attempt succeeds — the answer may have leaked.
    suspiciously_easy: bool


async def create_adjustment(
    db: AsyncSession,
    actor: User,
    *,
    points: int,
    reason: str,
    user_id: UUID | None = None,
    team_id: UUID | None = None,
    request_id: str | None = None,
) -> ScoreAdjustment:
    """Award or deduct points, from a player or from a party.

    A party adjustment belongs to the party itself — one row, no member touched.
    Not fanned out, and not routed through the leader: leadership transfers, and
    an adjustment attached to a person would leave the party with them while
    also moving them up the player board for points they did not earn.
    """
    if (user_id is None) == (team_id is None):
        raise InvalidAdjustment

    if user_id is not None:
        if await db.get(User, user_id) is None:
            raise NotFoundError("No such player.")
    else:
        team = await db.get(Team, team_id)
        if team is None:
            raise NotFoundError("No such party.")

    adjustment = ScoreAdjustment(
        user_id=user_id,
        team_id=team_id,
        points=points,
        reason=reason,
        created_by_user_id=actor.id,
    )
    db.add(adjustment)
    await db.flush()

    await record_audit(
        db,
        action="score.adjust",
        target_type="user" if user_id else "team",
        target_id=user_id or team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={
            "points": points,
            # Recorded plainly: an organiser adjusting their own score is not
            # forbidden, but it should never be quiet.
            "self_adjustment": bool(user_id and user_id == actor.id),
        },
        request_id=request_id,
    )
    return adjustment


async def reverse_adjustment(
    db: AsyncSession,
    actor: User,
    adjustment_id: UUID,
    reason: str,
    *,
    request_id: str | None = None,
) -> ScoreAdjustment:
    """Undo an adjustment by writing its opposite.

    Never a delete. The record of a decision people may argue about after the
    event is exactly what an audit trail is for.
    """
    original = await db.get(ScoreAdjustment, adjustment_id)
    if original is None:
        raise NotFoundError("No such adjustment.")
    if original.reverses_id is not None:
        raise ConflictError("That entry is itself a reversal.", code="adjustment_is_reversal")

    existing = await db.scalar(
        select(ScoreAdjustment.id).where(ScoreAdjustment.reverses_id == adjustment_id)
    )
    if existing is not None:
        raise ConflictError("That adjustment has already been reversed.", code="already_reversed")

    reversal = ScoreAdjustment(
        user_id=original.user_id,
        team_id=original.team_id,
        points=-original.points,
        reason=reason,
        created_by_user_id=actor.id,
        reverses_id=original.id,
    )
    db.add(reversal)
    await db.flush()

    await record_audit(
        db,
        action="score.reverse",
        target_type="user" if original.user_id else "team",
        target_id=original.user_id or original.team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"reverses": str(original.id), "points": -original.points},
        request_id=request_id,
    )
    return reversal


async def report_challenge(
    db: AsyncSession, user: User, challenge_id: UUID, message: str
) -> ChallengeReport:
    """A player says something is wrong. Idempotent while a report is open."""
    if await db.get(Challenge, challenge_id) is None:
        raise NotFoundError("No such challenge.")

    existing = await db.scalar(
        select(ChallengeReport).where(
            ChallengeReport.challenge_id == challenge_id,
            ChallengeReport.user_id == user.id,
            ChallengeReport.status == ReportStatus.OPEN,
        )
    )
    if existing is not None:
        return existing

    report = ChallengeReport(challenge_id=challenge_id, user_id=user.id, message=message)
    try:
        async with db.begin_nested():
            db.add(report)
    except IntegrityError:
        # Raced with themselves. Hand back whatever won.
        return await db.scalar(
            select(ChallengeReport).where(
                ChallengeReport.challenge_id == challenge_id,
                ChallengeReport.user_id == user.id,
                ChallengeReport.status == ReportStatus.OPEN,
            )
        )
    return report


async def set_report_status(
    db: AsyncSession,
    actor: User,
    report_id: UUID,
    status: ReportStatus,
    note: str | None,
    *,
    request_id: str | None = None,
) -> ChallengeReport:
    report = await db.get(ChallengeReport, report_id)
    if report is None:
        raise NotFoundError("No such report.")

    report.status = status
    report.resolution_note = note
    if status in (ReportStatus.RESOLVED, ReportStatus.DISMISSED):
        report.resolved_by_user_id = actor.id
        report.resolved_at = datetime.now(UTC)
    await db.flush()

    await record_audit(
        db,
        action="report.triage",
        target_type="challenge",
        target_id=report.challenge_id,
        actor_user_id=actor.id,
        reason=note,
        meta={"report_id": str(report.id), "status": status.value},
        request_id=request_id,
    )
    return report


async def challenge_health(db: AsyncSession) -> list[ChallengeHealth]:
    """Attempts against solves, per challenge.

    A challenge with eighty attempts and no solves at hour two means the answer
    rule is wrong, and finding that out from a screen rather than from a queue
    of complaints is most of the value of this dashboard.
    """
    challenges = (await db.execute(select(Challenge).order_by(Challenge.title))).scalars().all()
    if not challenges:
        return []

    solve_counts = dict(
        (
            await db.execute(select(Solve.challenge_id, func.count()).group_by(Solve.challenge_id))
        ).all()
    )
    attempt_counts = dict(
        (
            await db.execute(
                select(Submission.challenge_id, func.count()).group_by(Submission.challenge_id)
            )
        ).all()
    )
    report_counts = dict(
        (
            await db.execute(
                select(ChallengeReport.challenge_id, func.count())
                .where(ChallengeReport.status == ReportStatus.OPEN)
                .group_by(ChallengeReport.challenge_id)
            )
        ).all()
    )

    rows = []
    for challenge in challenges:
        solves = solve_counts.get(challenge.id, 0)
        attempts = attempt_counts.get(challenge.id, 0)
        # An untouched challenge is reported as untouched, not as a 0% success
        # rate and not as a division by zero.
        meaningful = attempts >= HEALTH_ATTEMPT_FLOOR
        rows.append(
            ChallengeHealth(
                challenge_id=challenge.id,
                title=challenge.title,
                state=challenge.state,
                solve_count=solves,
                attempt_count=attempts,
                open_reports=report_counts.get(challenge.id, 0),
                suspected_broken=meaningful and solves == 0,
                suspiciously_easy=meaningful and solves >= attempts * 0.95,
            )
        )
    return rows


def _since(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _count(db: AsyncSession, stmt: Select) -> int:
    return (await db.scalar(stmt)) or 0


#: How long a cached signal count is good for. Signals are six analyses over the
#: whole submission history — far too expensive to recompute on the sidebar's
#: 10-second poll, and a badge that is a minute stale is still a badge that gets
#: you to look.
SIGNAL_COUNT_TTL_SECONDS = 60
_SIGNAL_COUNT_KEY = "admin:nav:open_signals"


async def open_signal_count(db: AsyncSession, redis: Redis, settings: Settings) -> int:
    """Undismissed anti-cheat findings, cached.

    Falls back to reporting zero rather than failing the dashboard: a badge is
    the least important thing on the page, and the console has to render when
    Redis is unhappy.
    """
    try:
        cached = await redis.get(_SIGNAL_COUNT_KEY)
        if cached is not None:
            return int(cached)
    except Exception:
        logger.warning("nav_signal_count_cache_read_failed")

    results = await signals.compute(db, settings)
    total = sum(len(findings) for findings in results.values())

    try:
        await redis.set(_SIGNAL_COUNT_KEY, total, ex=SIGNAL_COUNT_TTL_SECONDS)
    except Exception:
        logger.warning("nav_signal_count_cache_write_failed")
    return total


async def nav_counts(db: AsyncSession, redis: Redis, settings: Settings) -> dict:
    """What the admin sidebar badges (spec 049 §5).

    Lives on the dashboard payload rather than four endpoints of its own: the
    shell already polls this one on a timer, and four more parallel polls from
    every open console is a self-inflicted load test.
    """
    return {
        "open_reports": await _count(
            db,
            select(func.count())
            .select_from(ChallengeReport)
            .where(ChallengeReport.status == ReportStatus.OPEN),
        ),
        "pending_approvals": await _count(
            db,
            select(func.count())
            .select_from(User)
            .where(User.status == UserStatus.PENDING_APPROVAL),
        ),
        "open_signals": await open_signal_count(db, redis, settings),
        "failed_instances": await _count(
            db,
            select(func.count())
            .select_from(ChallengeInstance)
            .where(ChallengeInstance.status == InstanceStatus.FAILED),
        ),
    }


async def dashboard(db: AsyncSession, redis: Redis, settings: Settings) -> dict:
    """The whole console in one response.

    One request rather than six: it refreshes on a timer, and six parallel polls
    from every open console is a self-inflicted load test.
    """
    now = datetime.now(UTC)
    event = await db.get(EventConfig, EVENT_CONFIG_ID)
    health = await challenge_health(db)

    published_ids = [c.challenge_id for c in health if c.state == ChallengeState.PUBLISHED]
    answerless = []
    if published_ids:
        with_answers = set(
            (
                await db.execute(
                    select(ChallengeAnswer.challenge_id).where(
                        ChallengeAnswer.challenge_id.in_(published_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        # Published with no answer rule is unsolvable by construction, and is
        # the kind of mistake nobody notices until players start complaining.
        answerless = [
            {"challenge_id": str(c.challenge_id), "title": c.title}
            for c in health
            if c.challenge_id in set(published_ids) and c.challenge_id not in with_answers
        ]

    drafts_after_start = 0
    if event is not None and event.has_started(now):
        drafts_after_start = await _count(
            db,
            select(func.count())
            .select_from(Challenge)
            .where(Challenge.state == ChallengeState.DRAFT),
        )

    return {
        "generated_at": now.isoformat(),
        "event": {
            "name": event.name if event else None,
            "starts_at": event.starts_at.isoformat() if event and event.starts_at else None,
            "ends_at": event.ends_at.isoformat() if event and event.ends_at else None,
            "running": bool(event and event.is_running(now)),
            "server_time": now.isoformat(),
        },
        "pulse": {
            "solves_5m": await _count(
                db, select(func.count()).select_from(Solve).where(Solve.submitted_at >= _since(5))
            ),
            "solves_15m": await _count(
                db, select(func.count()).select_from(Solve).where(Solve.submitted_at >= _since(15))
            ),
            "solves_60m": await _count(
                db, select(func.count()).select_from(Solve).where(Solve.submitted_at >= _since(60))
            ),
            "submissions_15m": await _count(
                db,
                select(func.count())
                .select_from(Submission)
                .where(Submission.created_at >= _since(15)),
            ),
            "active_players_15m": await _count(
                db,
                select(func.count(func.distinct(Submission.user_id))).where(
                    Submission.created_at >= _since(15)
                ),
            ),
        },
        "attention": {
            "open_reports": await _count(
                db,
                select(func.count())
                .select_from(ChallengeReport)
                .where(ChallengeReport.status == ReportStatus.OPEN),
            ),
            "pending_approvals": await _count(
                db,
                select(func.count())
                .select_from(User)
                .where(User.status == UserStatus.PENDING_APPROVAL),
            ),
            "drafts_after_start": drafts_after_start,
            "published_without_answers": answerless,
            "suspected_broken": [
                {"challenge_id": str(c.challenge_id), "title": c.title, "attempts": c.attempt_count}
                for c in health
                if c.suspected_broken
            ],
        },
        "nav_counts": await nav_counts(db, redis, settings),
        # Filled in by spec 009. A visible empty slot beats pretending.
        "containers": {"available": False, "note": "Instances arrive with spec 009."},
    }


async def bulk_release(
    db: AsyncSession,
    actor: User,
    challenge_ids: list[UUID],
    release_at: datetime | None,
    pre_release_state,  # noqa: ANN001 - PreReleaseState
    *,
    request_id: str | None = None,
) -> int:
    """Schedule a wave. A wave is several challenges sharing a release time."""
    challenges = (
        (await db.execute(select(Challenge).where(Challenge.id.in_(challenge_ids)))).scalars().all()
    )
    found = {challenge.id for challenge in challenges}
    missing = set(challenge_ids) - found
    if missing:
        raise NotFoundError(f"{len(missing)} of those challenges do not exist.")

    for challenge in challenges:
        challenge.release_at = release_at
        if pre_release_state is not None:
            challenge.pre_release_state = pre_release_state
        await record_audit(
            db,
            action="challenge.schedule",
            target_type="challenge",
            target_id=challenge.id,
            actor_user_id=actor.id,
            meta={
                "release_at": release_at.isoformat() if release_at else None,
                "pre_release_state": pre_release_state.value if pre_release_state else None,
            },
            request_id=request_id,
        )
    await db.flush()
    return len(challenges)
