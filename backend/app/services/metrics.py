"""Event-operations metrics (spec 050).

One purpose: **spotting a problem early enough to fix it mid-event.**

The dashboard already answers "is anything on fire right now?" — a five-minute
solve pulse and a needs-attention list. That is a smoke alarm: it catches a
challenge with zero solves and ninety attempts, and nothing subtler. This
answers the slower question, "is anything *drifting*?" A challenge twice as hard
as intended still produces solves, so it never trips the alarm; it just quietly
eats a day.

Deliberately not here: platform observability (spec 057 is one page, not a
stack), anti-cheat (spec 007 asks "is this player cheating?" — similar data,
opposite intent, and merging them would make every stalled player look like a
suspect), and final results (specs 051 and 056).
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging import get_logger
from app.models.challenge import Category, Challenge, ChallengeAnswer, ChallengeState, Difficulty
from app.models.hint import Hint, HintUnlock
from app.models.play import Solve, Submission
from app.models.user import User, UserRole, UserStatus
from app.services.scoring import level_for_xp

logger = get_logger(__name__)

#: These are aggregates over the whole submission history — by day five, on the
#: order of 10^5 rows. Small for Postgres, not small enough to recompute on
#: every ten-second poll. A metrics page a minute stale, that says so, is
#: strictly better than one that is live and costs a query storm.
CACHE_TTL_SECONDS = 60

WINDOWS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "today": timedelta(hours=24),
    "event": None,
}

#: Below this a per-challenge ratio is noise — one attempt and no solve is not a
#: signal, and early in an event most challenges look like that.
MIN_ATTEMPTS_TO_COMPARE = 8

#: Submitting, not solving, for this long.
STUCK_MINUTES = 60
#: Active earlier, nothing since.
QUIET_MINUTES = 120


def _since(window: str) -> datetime | None:
    delta = WINDOWS.get(window, WINDOWS["today"])
    return datetime.now(UTC) - delta if delta else None


def _window(stmt: Select, column, window: str) -> Select:
    since = _since(window)
    return stmt.where(column >= since) if since else stmt


async def cached(redis: Redis, key: str, build, *, ttl: int = CACHE_TTL_SECONDS) -> dict[str, Any]:
    """Serve from Redis where possible, and always say how fresh it is.

    A cache miss falls through to computing it; a Redis failure falls through
    to computing it too. The page must render when Redis is unhappy.
    """
    try:
        raw = await redis.get(key)
        if raw is not None:
            return json.loads(raw)
    except Exception:
        logger.warning("metrics_cache_read_failed", extra={"key": key})

    payload = await build()
    payload["generated_at"] = datetime.now(UTC).isoformat()
    try:
        await redis.set(key, json.dumps(payload, default=str), ex=ttl)
    except Exception:
        logger.warning("metrics_cache_write_failed", extra={"key": key})
    return payload


# --- Band 1: the pulse ------------------------------------------------------


async def pulse(db: AsyncSession, window: str) -> dict[str, Any]:
    """Six numbers, each against the previous equal-length window.

    A rate without a direction is not actionable, which is why every one of
    these carries a comparison.
    """
    since = _since(window)
    delta = WINDOWS.get(window) or timedelta(hours=24)
    previous_start = (since - delta) if since else None

    async def between(stmt: Select, start: datetime | None, end: datetime | None) -> int:
        if start is not None:
            stmt = stmt.where(Submission.created_at >= start)
        if end is not None:
            stmt = stmt.where(Submission.created_at < end)
        return int(await db.scalar(stmt) or 0)

    async def solves_between(start: datetime | None, end: datetime | None) -> int:
        stmt = select(func.count()).select_from(Solve)
        if start is not None:
            stmt = stmt.where(Solve.submitted_at >= start)
        if end is not None:
            stmt = stmt.where(Solve.submitted_at < end)
        return int(await db.scalar(stmt) or 0)

    solves = await solves_between(since, None)
    previous_solves = await solves_between(previous_start, since) if since else 0

    attempts = await between(select(func.count()).select_from(Submission), since, None)
    wrong = await between(
        select(func.count()).select_from(Submission).where(Submission.is_correct.is_(False)),
        since,
        None,
    )

    active = await between(select(func.count(func.distinct(Submission.user_id))), since, None)
    approved = int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.status == UserStatus.ACTIVE, User.role == UserRole.PLAYER)
        )
        or 0
    )

    hints_stmt = select(func.count()).select_from(HintUnlock)
    if since:
        hints_stmt = hints_stmt.where(HintUnlock.unlocked_at >= since)
    hints = int(await db.scalar(hints_stmt) or 0)

    # Players whose first solve landed inside the window — the on-ramp working,
    # or not.
    first_solves = (
        select(Solve.user_id, func.min(Solve.submitted_at).label("first_at"))
        .group_by(Solve.user_id)
        .subquery()
    )
    newcomers_stmt = select(func.count()).select_from(first_solves)
    if since:
        newcomers_stmt = newcomers_stmt.where(first_solves.c.first_at >= since)
    newcomers = int(await db.scalar(newcomers_stmt) or 0)

    hours = (delta.total_seconds() / 3600) if delta else max((solves and 1) or 1, 1)

    return {
        "window": window,
        "solves": solves,
        "solves_previous": previous_solves,
        "solves_per_hour": round(solves / hours, 1) if hours else 0.0,
        # The single best early warning: it climbs before solves fall.
        "attempts_per_solve": round(attempts / solves, 2) if solves else 0.0,
        "wrong_attempts": wrong,
        "active_players": active,
        "approved_players": approved,
        # 40 active out of 200 approved is a different event from 40 out of 45.
        "participation": round(active / approved, 3) if approved else 0.0,
        "hints_unlocked": hints,
        "first_time_solvers": newcomers,
    }


# --- Band 2: challenges drifting -------------------------------------------


def _fold(value: str) -> str:
    return " ".join(value.split()).casefold()


def _within_two(a: str, b: str) -> bool:
    if a == b:
        return True
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > 2:
            return False
        previous = current
    return previous[-1] <= 2


async def challenges(
    db: AsyncSession, window: str, *, category_id: Any = None, difficulty: str | None = None
) -> dict[str, Any]:
    since = _since(window)

    rows = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                Challenge.difficulty,
                Challenge.state,
                Category.name,
            ).outerjoin(Category, Category.id == Challenge.category_id)
        )
    ).all()

    attempt_stmt = select(Submission.challenge_id, func.count()).group_by(Submission.challenge_id)
    solve_stmt = select(Solve.challenge_id, func.count()).group_by(Solve.challenge_id)
    if since:
        attempt_stmt = attempt_stmt.where(Submission.created_at >= since)
        solve_stmt = solve_stmt.where(Solve.submitted_at >= since)

    attempts = dict((await db.execute(attempt_stmt)).all())
    solves = dict((await db.execute(solve_stmt)).all())

    # HintUnlock points at a hint, not a challenge; the challenge is one join
    # further out.
    hint_uptake = dict(
        (
            await db.execute(
                select(Hint.challenge_id, func.count(func.distinct(HintUnlock.user_id)))
                .join(Hint, Hint.id == HintUnlock.hint_id)
                .group_by(Hint.challenge_id)
            )
        ).all()
    )

    near_miss = await _near_miss_rates(db, since)

    per_difficulty: dict[str, list[float]] = {}
    computed = []
    for challenge_id, title, diff, state, zone in rows:
        seen = int(attempts.get(challenge_id, 0))
        solved = int(solves.get(challenge_id, 0))
        ratio = (seen / solved) if solved else float(seen)
        computed.append(
            {
                "challenge_id": str(challenge_id),
                "title": title,
                "zone": zone,
                "difficulty": diff.value if isinstance(diff, Difficulty) else str(diff),
                "state": state.value if isinstance(state, ChallengeState) else str(state),
                "attempts": seen,
                "solves": solved,
                "attempts_per_solve": round(ratio, 2),
                "hint_uptake": int(hint_uptake.get(challenge_id, 0)),
                # Never the strings themselves — a wrong submission is as good
                # as a hint, so the page receives a rate and no examples.
                "near_miss_rate": near_miss.get(challenge_id, 0.0),
            }
        )
        if seen >= MIN_ATTEMPTS_TO_COMPARE and solved:
            per_difficulty.setdefault(computed[-1]["difficulty"], []).append(ratio)

    medians = {
        band: sorted(values)[len(values) // 2] for band, values in per_difficulty.items() if values
    }

    for row in computed:
        median = medians.get(row["difficulty"])
        if row["attempts"] < MIN_ATTEMPTS_TO_COMPARE or not median:
            # Early in an event most challenges have too few attempts to
            # compare; a multiple computed from three attempts is a lie.
            row["vs_difficulty"] = None
        else:
            row["vs_difficulty"] = round(row["attempts_per_solve"] / median, 2)

    if category_id:
        computed = [row for row in computed if row["zone"] == category_id]
    if difficulty:
        computed = [row for row in computed if row["difficulty"] == difficulty]

    # Ranked by concern rather than alphabetically. The ordering is not shown;
    # the columns are what an admin reads.
    computed.sort(
        key=lambda row: (
            row["vs_difficulty"] or 0,
            row["near_miss_rate"],
            row["attempts_per_solve"],
        ),
        reverse=True,
    )

    return {"window": window, "challenges": computed, "difficulty_medians": medians}


async def _near_miss_rates(db: AsyncSession, since: datetime | None) -> dict[Any, float]:
    """Wrong answers that were nearly right.

    A challenge where people repeatedly submit something *almost* right is not
    too hard — it has a **format problem**: case, whitespace, a wrapper the
    description never mentioned. This is the clearest "fix the answer rule, not
    the challenge" signal available, and the one most likely to save a day.

    Computed here and never sent onward: the strings and their distances are as
    good as a hint.
    """
    answers: dict[Any, set[str]] = {}
    for challenge_id, value in (
        await db.execute(select(ChallengeAnswer.challenge_id, ChallengeAnswer.value))
    ).all():
        if value:
            answers.setdefault(challenge_id, set()).add(_fold(value))
    if not answers:
        return {}

    stmt = select(Submission.challenge_id, Submission.submitted_value).where(
        Submission.is_correct.is_(False)
    )
    if since:
        stmt = stmt.where(Submission.created_at >= since)

    totals: dict[Any, int] = {}
    close: dict[Any, int] = {}
    for challenge_id, value in (await db.execute(stmt)).all():
        expected = answers.get(challenge_id)
        if not expected or not value:
            continue
        totals[challenge_id] = totals.get(challenge_id, 0) + 1
        candidate = _fold(value)
        # A near miss the checker would have accepted is not a near miss; it is
        # a solve, and counting it would blame the wrong thing.
        if candidate in expected:
            continue
        if any(_within_two(candidate, answer) for answer in expected):
            close[challenge_id] = close.get(challenge_id, 0) + 1

    return {
        challenge_id: round(close.get(challenge_id, 0) / total, 3)
        for challenge_id, total in totals.items()
        if total
    }


# --- Band 3: players stalled ------------------------------------------------


async def players(db: AsyncSession, kind: str = "stuck") -> dict[str, Any]:
    """Who to go and talk to.

    Ignores the window control deliberately (spec 050 §10.2): "stalled" is
    inherently about the recent past, and a whole-event window would make every
    filter here meaningless.
    """
    now = datetime.now(UTC)

    last_solve = dict(
        (
            await db.execute(
                select(Solve.user_id, func.max(Solve.submitted_at)).group_by(Solve.user_id)
            )
        ).all()
    )
    last_submission = dict(
        (
            await db.execute(
                select(Submission.user_id, func.max(Submission.created_at)).group_by(
                    Submission.user_id
                )
            )
        ).all()
    )
    totals = {
        row[0]: (int(row[1]), int(row[2]))
        for row in (
            await db.execute(
                select(
                    Solve.user_id, func.count(), func.coalesce(func.sum(Solve.xp_awarded), 0)
                ).group_by(Solve.user_id)
            )
        ).all()
    }
    hints = dict(
        (
            await db.execute(select(HintUnlock.user_id, func.count()).group_by(HintUnlock.user_id))
        ).all()
    )

    roster = (
        (
            await db.execute(
                select(User).where(User.status == UserStatus.ACTIVE, User.role == UserRole.PLAYER)
            )
        )
        .scalars()
        .all()
    )

    walls = await _current_walls(db, [user.id for user in roster])
    base = get_settings().xp_level_base

    rows = []
    for user in roster:
        solved_at = last_solve.get(user.id)
        tried_at = last_submission.get(user.id)
        solves, xp = totals.get(user.id, (0, 0))

        stuck = (
            tried_at is not None
            and (now - tried_at).total_seconds() < STUCK_MINUTES * 60
            and (solved_at is None or (now - solved_at).total_seconds() > STUCK_MINUTES * 60)
        )
        quiet = tried_at is not None and (now - tried_at).total_seconds() > QUIET_MINUTES * 60
        never = tried_at is None

        if kind == "stuck" and not stuck:
            continue
        if kind == "quiet" and not quiet:
            continue
        if kind == "never_started" and not never:
            continue

        rows.append(
            {
                "user_id": str(user.id),
                "display_name": user.display_name,
                "solves": solves,
                "xp": xp,
                "level": level_for_xp(xp, base),
                "last_solve_at": solved_at.isoformat() if solved_at else None,
                # Distinguishes *stopped playing* from *stuck and trying*.
                "last_submission_at": tried_at.isoformat() if tried_at else None,
                "current_wall": walls.get(user.id),
                "hints_used": int(hints.get(user.id, 0)),
            }
        )

    rows.sort(key=lambda row: (row["last_solve_at"] or "", row["display_name"]))
    return {"filter": kind, "players": rows}


async def _current_walls(db: AsyncSession, user_ids: list[Any]) -> dict[Any, str | None]:
    """The challenge each player most recently attempted without solving."""
    if not user_ids:
        return {}

    solved = select(Solve.user_id, Solve.challenge_id).subquery()
    rows = (
        await db.execute(
            select(Submission.user_id, Challenge.title, Submission.created_at)
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .outerjoin(
                solved,
                (solved.c.user_id == Submission.user_id)
                & (solved.c.challenge_id == Submission.challenge_id),
            )
            .where(Submission.user_id.in_(user_ids), solved.c.challenge_id.is_(None))
            .order_by(Submission.created_at.desc())
        )
    ).all()

    walls: dict[Any, str | None] = {}
    for user_id, title, _at in rows:
        walls.setdefault(user_id, title)
    return walls


# --- Band 4: progression and economy ---------------------------------------


async def progression(db: AsyncSession) -> dict[str, Any]:
    base = get_settings().xp_level_base

    xp_rows = (
        await db.execute(
            select(Solve.user_id, func.coalesce(func.sum(Solve.xp_awarded), 0)).group_by(
                Solve.user_id
            )
        )
    ).all()
    levels: dict[int, int] = {}
    for _user_id, xp in xp_rows:
        level = level_for_xp(int(xp or 0), base)
        levels[level] = levels.get(level, 0) + 1

    zone_rows = (
        await db.execute(
            select(Category.name, func.count(func.distinct(Solve.user_id)))
            .join(Challenge, Challenge.category_id == Category.id)
            .join(Solve, Solve.challenge_id == Challenge.id)
            .group_by(Category.name)
        )
    ).all()

    category_health = (
        await db.execute(
            select(
                Category.name,
                func.count(func.distinct(Submission.id)),
                func.count(func.distinct(Solve.id)),
            )
            .join(Challenge, Challenge.category_id == Category.id)
            .outerjoin(Submission, Submission.challenge_id == Challenge.id)
            .outerjoin(Solve, Solve.challenge_id == Challenge.id)
            .group_by(Category.name)
        )
    ).all()

    hint_total = int(await db.scalar(select(func.count()).select_from(HintUnlock)) or 0)
    players_with_hints = int(
        await db.scalar(select(func.count(func.distinct(HintUnlock.user_id)))) or 0
    )
    solves_total = int(await db.scalar(select(func.count()).select_from(Solve)) or 0)

    return {
        "levels": [{"level": level, "players": count} for level, count in sorted(levels.items())],
        "zone_spread": [{"zone": zone, "players": int(count)} for zone, count in zone_rows],
        "category_health": [
            {
                "zone": zone,
                "attempts": int(attempts),
                "solves": int(solved),
                "attempts_per_solve": round(attempts / solved, 2) if solved else 0.0,
            }
            for zone, attempts, solved in category_health
        ],
        "hints": {
            "unlocked": hint_total,
            "players_using": players_with_hints,
            # Hints cost points (spec 004), so an unused hint system and an
            # over-used one are both problems.
            "hints_per_solve": round(hint_total / solves_total, 3) if solves_total else 0.0,
        },
    }


async def cached_pulse(db: AsyncSession, redis: Redis, window: str) -> dict[str, Any]:
    return await cached(redis, f"metrics:pulse:{window}", lambda: pulse(db, window))


async def cached_challenges(
    db: AsyncSession, redis: Redis, window: str, **filters: Any
) -> dict[str, Any]:
    key = f"metrics:challenges:{window}:{filters.get('category_id')}:{filters.get('difficulty')}"
    return await cached(redis, key, lambda: challenges(db, window, **filters))


async def cached_players(db: AsyncSession, redis: Redis, kind: str) -> dict[str, Any]:
    return await cached(redis, f"metrics:players:{kind}", lambda: players(db, kind))


async def cached_progression(db: AsyncSession, redis: Redis) -> dict[str, Any]:
    return await cached(redis, "metrics:progression", lambda: progression(db))


__all__ = [
    "CACHE_TTL_SECONDS",
    "MIN_ATTEMPTS_TO_COMPARE",
    "cached_challenges",
    "cached_players",
    "cached_progression",
    "cached_pulse",
    "challenges",
    "players",
    "progression",
    "pulse",
]
