"""Achievements: what a player did, noticed (spec 028).

A trigger is a **predicate over the player's stored history**, not a hook on an
event payload. That is what keeps one writable at all: "three solves inside five
minutes" or "ten wrong flags on one challenge" is a single query, where
threading enough context through every call site to answer it live would not be.
The history is already there — every submission right or wrong is timestamped,
as is every solve and hint unlock.

**There is no backfill.** An achievement created after the fact awards nothing
for work already done; the roster is seeded before the event starts. Triggers
therefore only ever run forward, after the events that could change their answer.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.challenge import (
    BOSS_TIER_LEVEL,
    Ability,
    Category,
    Challenge,
    ChallengeState,
    Difficulty,
)
from app.models.character_class import Rarity
from app.models.event import EventConfig
from app.models.guardrail import AssistantFinding, GuardrailLayer
from app.models.hint import Hint, HintUnlock
from app.models.instance import ChallengeInstance, InstanceStatus
from app.models.notification import (
    Achievement,
    AchievementAward,
    NotificationKind,
)
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.player_event import PlayerEventKind
from app.models.puzzle import ChallengePuzzle, PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.report import ChallengeReport, ReportStatus
from app.models.team import Team, TeamMembership
from app.models.theme_unlock import UnlockSource
from app.models.user import User
from app.services import narrator, notifications, player_events, scoring, theme_unlocks

#: The events that can change a trigger's answer. A trigger declares which it
#: cares about so a solve does not re-run every unrelated query in the roster.
SOLVE = "solve"
#: Every attempt, right or wrong. The highest-frequency event on the platform,
#: so only the few triggers that genuinely need it may listen (spec 029).
SUBMIT = "submit"
HINT = "hint"
CLASS = "class"
PARTY = "party"
ASSISTANT = "assistant"
INSTANCE = "instance"
#: Things that happened *to* the player rather than something they did on
#: purpose — a 500, a closed admin door, a change of class (spec 039). Recorded
#: on the failure path and counted here, so the award lands on the next ordinary
#: action rather than mid-crash.
PLATFORM = "platform"


@dataclass(frozen=True)
class Trigger:
    events: frozenset[str]
    check: Callable[[AsyncSession, UUID], Awaitable[bool]]


REGISTRY: dict[str, Trigger] = {}
#: Triggers whose code is not known until the data is. A boss achievement is
#: ``boss_<zone-slug>``, and zones are rows rather than code, so the family is
#: registered once and the code resolved against it (spec 031).
PREFIX_TRIGGERS: list[tuple[str, frozenset[str], Callable[[str], object]]] = []


def prefix_trigger(prefix: str, *events: str):
    """Register a family of triggers sharing a code prefix.

    The factory receives whatever followed the prefix and returns the check.
    """

    def register(factory):
        PREFIX_TRIGGERS.append((prefix, frozenset(events), factory))
        return factory

    return register


def resolve(code: str) -> Trigger | None:
    """The trigger that awards ``code``, exact match or prefix family.

    Returns None for a code nothing implements, which is the inert state the
    admin roster surfaces rather than an error.
    """
    exact = REGISTRY.get(code)
    if exact is not None:
        return exact
    for prefix, events, factory in PREFIX_TRIGGERS:
        if code.startswith(prefix) and len(code) > len(prefix):
            return Trigger(events=events, check=factory(code[len(prefix) :]))
    return None


#: The prefix families, for the admin roster to describe.
def trigger_families() -> list[str]:
    return [f"{prefix}<slug>" for prefix, _events, _factory in PREFIX_TRIGGERS]


def trigger(code: str, *events: str):
    """Register the predicate that awards ``code``."""

    def register(fn: Callable[[AsyncSession, UUID], Awaitable[bool]]):
        REGISTRY[code] = Trigger(events=frozenset(events), check=fn)
        return fn

    return register


# --- The starter set -------------------------------------------------------
# Enough to prove the machinery end to end. The real roster arrives as seed data
# and only needs a trigger registered against its code.


@trigger("first_blood", SOLVE)
async def _first_solve(db: AsyncSession, user_id: UUID) -> bool:
    """Solved anything at all."""
    return bool(await db.scalar(select(Solve.id).where(Solve.user_id == user_id).limit(1)))


@trigger("getting_comfortable", SOLVE)
async def _ten_solves(db: AsyncSession, user_id: UUID) -> bool:
    count = await db.scalar(select(func.count(Solve.id)).where(Solve.user_id == user_id))
    return (count or 0) >= 10


@trigger("clean_sweep", SOLVE)
async def _cleared_a_zone(db: AsyncSession, user_id: UUID) -> bool:
    """Every published challenge in some category, solved."""
    published = (
        await db.execute(
            select(Challenge.category_id, func.count(Challenge.id))
            .where(Challenge.state == ChallengeState.PUBLISHED)
            .group_by(Challenge.category_id)
        )
    ).all()
    solved = dict(
        (
            await db.execute(
                select(Challenge.category_id, func.count(Solve.id))
                .join(Solve, Solve.challenge_id == Challenge.id)
                .where(Solve.user_id == user_id, Challenge.state == ChallengeState.PUBLISHED)
                .group_by(Challenge.category_id)
            )
        ).all()
    )
    return any(
        total > 0 and solved.get(category_id, 0) >= total for category_id, total in published
    )


@trigger("stubborn", SOLVE)
async def _ten_wrong_on_one(db: AsyncSession, user_id: UUID) -> bool:
    """Ten wrong flags on a single challenge, and solved it anyway."""
    worst = await db.scalar(
        select(func.count(Submission.id))
        .where(Submission.user_id == user_id, Submission.is_correct.is_(False))
        .group_by(Submission.challenge_id)
        .order_by(func.count(Submission.id).desc())
        .limit(1)
    )
    return (worst or 0) >= 10


@trigger("blitz", SOLVE)
async def _three_in_five_minutes(db: AsyncSession, user_id: UUID) -> bool:
    """Three solves inside five minutes."""
    times = (
        (
            await db.execute(
                select(Solve.submitted_at)
                .where(Solve.user_id == user_id)
                .order_by(Solve.submitted_at)
            )
        )
        .scalars()
        .all()
    )
    window = timedelta(minutes=5)
    return any(times[index + 2] - times[index] <= window for index in range(len(times) - 2))


@trigger("well_rounded", SOLVE)
async def _five_categories(db: AsyncSession, user_id: UUID) -> bool:
    """Solved something in five different zones."""
    count = await db.scalar(
        select(func.count(distinct(Challenge.category_id)))
        .join(Solve, Solve.challenge_id == Challenge.id)
        .where(Solve.user_id == user_id)
    )
    return (count or 0) >= 5


# --- Solve volume, breadth and difficulty ----------------------------------


async def _solve_count(db: AsyncSession, user_id: UUID) -> int:
    return (await db.scalar(select(func.count(Solve.id)).where(Solve.user_id == user_id))) or 0


@trigger("regular", SOLVE)
async def _regular(db: AsyncSession, user_id: UUID) -> bool:
    return await _solve_count(db, user_id) >= 25


@trigger("prolific", SOLVE)
async def _prolific(db: AsyncSession, user_id: UUID) -> bool:
    return await _solve_count(db, user_id) >= 50


@trigger("centurion", SOLVE)
async def _centurion(db: AsyncSession, user_id: UUID) -> bool:
    return await _solve_count(db, user_id) >= 100


async def _zones_touched(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(distinct(Challenge.category_id)))
            .join(Solve, Solve.challenge_id == Challenge.id)
            .where(Solve.user_id == user_id)
        )
    ) or 0


@trigger("wayfarer", SOLVE)
async def _wayfarer(db: AsyncSession, user_id: UUID) -> bool:
    return await _zones_touched(db, user_id) >= 10


@trigger("everywhere", SOLVE)
async def _everywhere(db: AsyncSession, user_id: UUID) -> bool:
    return await _zones_touched(db, user_id) >= 20


async def _difficulties_solved(db: AsyncSession, user_id: UUID) -> set:
    rows = (
        (
            await db.execute(
                select(distinct(Challenge.difficulty))
                .join(Solve, Solve.challenge_id == Challenge.id)
                .where(Solve.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


@trigger("stepping_up", SOLVE)
async def _stepping_up(db: AsyncSession, user_id: UUID) -> bool:
    return Difficulty.MEDIUM in await _difficulties_solved(db, user_id)


@trigger("heavy_lifting", SOLVE)
async def _heavy_lifting(db: AsyncSession, user_id: UUID) -> bool:
    return Difficulty.HARD in await _difficulties_solved(db, user_id)


@trigger("into_the_deep", SOLVE)
async def _into_the_deep(db: AsyncSession, user_id: UUID) -> bool:
    return Difficulty.VERY_HARD in await _difficulties_solved(db, user_id)


@trigger("against_the_odds", SOLVE)
async def _against_the_odds(db: AsyncSession, user_id: UUID) -> bool:
    return Difficulty.NEARLY_IMPOSSIBLE in await _difficulties_solved(db, user_id)


@trigger("full_spectrum", SOLVE)
async def _full_spectrum(db: AsyncSession, user_id: UUID) -> bool:
    return await _difficulties_solved(db, user_id) >= set(Difficulty)


@trigger("backwards", SOLVE)
async def _backwards(db: AsyncSession, user_id: UUID) -> bool:
    """A nearly-impossible solve before any very-easy one."""
    rows = (
        await db.execute(
            select(Challenge.difficulty, Solve.submitted_at)
            .join(Solve, Solve.challenge_id == Challenge.id)
            .where(Solve.user_id == user_id)
            .order_by(Solve.submitted_at)
        )
    ).all()
    for difficulty, _ in rows:
        if difficulty is Difficulty.NEARLY_IMPOSSIBLE:
            return True
        if difficulty is Difficulty.VERY_EASY:
            return False
    return False


@trigger("clean_hands", SOLVE)
async def _clean_hands(db: AsyncSession, user_id: UUID) -> bool:
    """Ten challenges solved without a single wrong answer on them."""
    wrong = (
        (
            await db.execute(
                select(distinct(Submission.challenge_id)).where(
                    Submission.user_id == user_id, Submission.is_correct.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    stmt = select(func.count(Solve.id)).where(Solve.user_id == user_id)
    if wrong:
        stmt = stmt.where(Solve.challenge_id.not_in(wrong))
    return ((await db.scalar(stmt)) or 0) >= 10


@trigger("unfinished_business", SOLVE)
async def _unfinished_business(db: AsyncSession, user_id: UUID) -> bool:
    """Solved something over a day after first attempting it."""
    first_try = (
        select(
            Submission.challenge_id.label("cid"),
            func.min(Submission.created_at).label("started"),
        )
        .where(Submission.user_id == user_id)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    gap = await db.scalar(
        select(func.count(Solve.id))
        .join(first_try, first_try.c.cid == Solve.challenge_id)
        .where(
            Solve.user_id == user_id,
            Solve.submitted_at > first_try.c.started + timedelta(days=1),
        )
    )
    return (gap or 0) >= 1


@trigger("first_through", SOLVE)
async def _first_through(db: AsyncSession, user_id: UUID) -> bool:
    return await _first_blood_count(db, user_id) >= 1


@trigger("pathfinder", SOLVE)
async def _pathfinder(db: AsyncSession, user_id: UUID) -> bool:
    return await _first_blood_count(db, user_id) >= 10


async def _first_blood_count(db: AsyncSession, user_id: UUID) -> int:
    """How many challenges this player solved before anyone else.

    Earliest ``submitted_at`` wins; the solve unique constraint means one row
    per player, and a tie to the microsecond is not worth modelling.
    """
    earliest = (
        select(
            Solve.challenge_id.label("cid"),
            func.min(Solve.submitted_at).label("first"),
        )
        .group_by(Solve.challenge_id)
        .subquery()
    )
    return (
        await db.scalar(
            select(func.count(Solve.id))
            .join(earliest, earliest.c.cid == Solve.challenge_id)
            .where(Solve.user_id == user_id, Solve.submitted_at == earliest.c.first)
        )
    ) or 0


def _local_hour(moment: datetime) -> int:
    """The hour as the players experienced it.

    Timestamps are stored UTC and the event runs in one place, so "01:00" has to
    mean 01:00 there rather than 01:00 UTC.
    """
    offset = get_settings().event_utc_offset_hours
    return (moment.hour + offset) % 24


@trigger("night_shift", SOLVE)
async def _night_shift(db: AsyncSession, user_id: UUID) -> bool:
    times = await _solve_times(db, user_id)
    return any(1 <= _local_hour(t) < 5 for t in times)


async def _solve_times(db: AsyncSession, user_id: UUID) -> list:
    return list(
        (
            await db.execute(
                select(Solve.submitted_at)
                .where(Solve.user_id == user_id)
                .order_by(Solve.submitted_at)
            )
        )
        .scalars()
        .all()
    )


@trigger("fast_start", SOLVE)
async def _fast_start(db: AsyncSession, user_id: UUID) -> bool:
    """Ten solves inside the event's first day.

    Returns false rather than guessing when the event has no start time — an
    unconfigured event cannot answer this question.
    """
    starts_at = await db.scalar(select(EventConfig.starts_at))
    if starts_at is None:
        return False
    count = await db.scalar(
        select(func.count(Solve.id)).where(
            Solve.user_id == user_id,
            Solve.submitted_at < starts_at + timedelta(days=1),
        )
    )
    return (count or 0) >= 10


# --- Zones cleared ---------------------------------------------------------


async def _zones_cleared(db: AsyncSession, user_id: UUID) -> set:
    """Categories where this player has solved every published challenge."""
    published = (
        await db.execute(
            select(Challenge.category_id, func.count(Challenge.id))
            .where(Challenge.state == ChallengeState.PUBLISHED)
            .group_by(Challenge.category_id)
        )
    ).all()
    solved = dict(
        (
            await db.execute(
                select(Challenge.category_id, func.count(Solve.id))
                .join(Solve, Solve.challenge_id == Challenge.id)
                .where(Solve.user_id == user_id, Challenge.state == ChallengeState.PUBLISHED)
                .group_by(Challenge.category_id)
            )
        ).all()
    )
    return {
        category_id
        for category_id, total in published
        if total > 0 and solved.get(category_id, 0) >= total
    }


@trigger("double_clear", SOLVE)
async def _double_clear(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _zones_cleared(db, user_id)) >= 2


@trigger("conqueror", SOLVE)
async def _conqueror(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _zones_cleared(db, user_id)) >= 5


@trigger("whole_dungeon", SOLVE)
async def _whole_dungeon(db: AsyncSession, user_id: UUID) -> bool:
    """Every zone that has anything in it."""
    with_content = set(
        (
            await db.execute(
                select(distinct(Challenge.category_id)).where(
                    Challenge.state == ChallengeState.PUBLISHED
                )
            )
        )
        .scalars()
        .all()
    )
    if not with_content:
        return False
    return with_content <= await _zones_cleared(db, user_id)


@trigger("flawless", SOLVE)
async def _flawless(db: AsyncSession, user_id: UUID) -> bool:
    """Cleared a zone without a wrong flag in it.

    Only wrong answers submitted *before* the zone was finished count — one
    typed afterwards must not retroactively spoil it.
    """
    for category_id in await _zones_cleared(db, user_id):
        finished = await db.scalar(
            select(func.max(Solve.submitted_at))
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Solve.user_id == user_id, Challenge.category_id == category_id)
        )
        wrong = await db.scalar(
            select(func.count(Submission.id))
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .where(
                Submission.user_id == user_id,
                Submission.is_correct.is_(False),
                Challenge.category_id == category_id,
                Submission.created_at <= finished,
            )
        )
        if not wrong:
            return True
    return False


# --- Levels, abilities and skills ------------------------------------------


async def _level(db: AsyncSession, user_id: UUID) -> int:
    return scoring.level_for_xp(await scoring.total_xp(db, user_id))


@trigger("journeyman", SOLVE)
async def _journeyman(db: AsyncSession, user_id: UUID) -> bool:
    return await _level(db, user_id) >= 5


@trigger("veteran", SOLVE)
async def _veteran(db: AsyncSession, user_id: UUID) -> bool:
    return await _level(db, user_id) >= 10


@trigger("ascendant", SOLVE)
async def _ascendant(db: AsyncSession, user_id: UUID) -> bool:
    return await _level(db, user_id) >= 15


@trigger("maximum", SOLVE)
async def _maximum(db: AsyncSession, user_id: UUID) -> bool:
    return await _level(db, user_id) >= get_settings().player_level_cap


async def _ability_scores(db: AsyncSession, user_id: UUID) -> list[int]:
    banked = await scoring.ability_xp_for_user(db, user_id)
    return [scoring.ability_score(banked.get(ability, 0)) for ability in Ability]


@trigger("above_average", SOLVE)
async def _above_average(db: AsyncSession, user_id: UUID) -> bool:
    return max(await _ability_scores(db, user_id), default=0) >= 12


@trigger("formidable", SOLVE)
async def _formidable(db: AsyncSession, user_id: UUID) -> bool:
    return max(await _ability_scores(db, user_id), default=0) >= 16


@trigger("peak", SOLVE)
async def _peak(db: AsyncSession, user_id: UUID) -> bool:
    return max(await _ability_scores(db, user_id), default=0) >= 20


@trigger("balanced_build", SOLVE)
async def _balanced_build(db: AsyncSession, user_id: UUID) -> bool:
    scores = await _ability_scores(db, user_id)
    return bool(scores) and min(scores) >= 12


@trigger("complete", SOLVE)
async def _complete(db: AsyncSession, user_id: UUID) -> bool:
    scores = await _ability_scores(db, user_id)
    return bool(scores) and min(scores) >= 16


async def _best_skill_level(db: AsyncSession, user_id: UUID) -> int:
    banked = await scoring.skill_xp_for_user(db, user_id)
    return max((scoring.skill_level(xp) for xp in banked.values()), default=0)


@trigger("specialist", SOLVE)
async def _specialist(db: AsyncSession, user_id: UUID) -> bool:
    return await _best_skill_level(db, user_id) >= 5


@trigger("expert", SOLVE)
async def _expert(db: AsyncSession, user_id: UUID) -> bool:
    return await _best_skill_level(db, user_id) >= 10


@trigger("master", SOLVE)
async def _master(db: AsyncSession, user_id: UUID) -> bool:
    return await _best_skill_level(db, user_id) >= get_settings().skill_level_cap


@trigger("doorway", SOLVE)
async def _doorway(db: AsyncSession, user_id: UUID) -> bool:
    """A second zone open. Ungated zones count — they are open from the start."""
    from app.services import progress

    return len(await progress._open_zones(db, user_id)) >= 2


# --- Class ------------------------------------------------------------------


@trigger("know_thyself", CLASS)
async def _know_thyself(db: AsyncSession, user_id: UUID) -> bool:
    return bool(await db.scalar(select(User.character_class_id).where(User.id == user_id)))


async def _unlocked_rarities(db: AsyncSession, user_id: UUID) -> set:
    from app.services import classes as class_service

    return {
        standing.character_class.rarity
        for standing in await class_service.standings(db, user_id)
        if standing.unlocked
    }


@trigger("rare_breed", SOLVE)
async def _rare_breed(db: AsyncSession, user_id: UUID) -> bool:
    """Reads *unlocked*, not chosen: qualifying is the achievement."""
    return bool(
        await _unlocked_rarities(db, user_id) & {Rarity.RARE, Rarity.LEGENDARY, Rarity.MYTHIC}
    )


@trigger("mythic", SOLVE)
async def _mythic(db: AsyncSession, user_id: UUID) -> bool:
    return Rarity.MYTHIC in await _unlocked_rarities(db, user_id)


@trigger("against_type", CLASS)
async def _against_type(db: AsyncSession, user_id: UUID) -> bool:
    """Chose a class none of whose preference targets you are strongest in."""
    from app.services import classes as class_service

    chosen_id = await db.scalar(select(User.character_class_id).where(User.id == user_id))
    if chosen_id is None:
        return False
    ranked = sorted(
        await class_service.standings(db, user_id),
        key=lambda s: -s.affinity,
    )
    scoring_any = [s for s in ranked if s.affinity > 0]
    if not scoring_any:
        return False
    # In the bottom half of what actually fits them.
    chosen = next((s for s in ranked if s.character_class.id == chosen_id), None)
    return chosen is not None and chosen.affinity == 0


# --- Hints ------------------------------------------------------------------


@trigger("asking_directions", HINT)
async def _asking_directions(db: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await db.scalar(select(HintUnlock.id).where(HintUnlock.user_id == user_id).limit(1))
    )


@trigger("net_negative", HINT)
async def _net_negative(db: AsyncSession, user_id: UUID) -> bool:
    """Spent more on hints for one challenge than the challenge was worth."""
    rows = (
        await db.execute(
            select(
                Hint.challenge_id,
                func.sum(HintUnlock.cost_charged),
                Challenge.initial_points,
            )
            .join(Hint, Hint.id == HintUnlock.hint_id)
            .join(Challenge, Challenge.id == Hint.challenge_id)
            .where(HintUnlock.user_id == user_id)
            .group_by(Hint.challenge_id, Challenge.initial_points)
        )
    ).all()
    return any(spent > worth for _, spent, worth in rows)


@trigger("out_of_road", SUBMIT)
async def _out_of_road(db: AsyncSession, user_id: UUID) -> bool:
    """Used every attempt on a limited challenge without solving it."""
    solved = select(Solve.challenge_id).where(Solve.user_id == user_id)
    rows = (
        await db.execute(
            select(Submission.challenge_id, func.count(Submission.id), Challenge.max_attempts)
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .where(
                Submission.user_id == user_id,
                Challenge.max_attempts.is_not(None),
                Submission.challenge_id.not_in(solved),
            )
            .group_by(Submission.challenge_id, Challenge.max_attempts)
        )
    ).all()
    return any(used >= limit for _, used, limit in rows)


# --- Getting it wrong -------------------------------------------------------


async def _wrong_count(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(Submission.id)).where(
                Submission.user_id == user_id, Submission.is_correct.is_(False)
            )
        )
    ) or 0


@trigger("working_theory", SUBMIT)
async def _working_theory(db: AsyncSession, user_id: UUID) -> bool:
    return await _wrong_count(db, user_id) >= 1


@trigger("volume_approach", SUBMIT)
async def _volume_approach(db: AsyncSession, user_id: UUID) -> bool:
    return await _wrong_count(db, user_id) >= 50


@trigger("brute_force_strategy", SUBMIT)
async def _brute_force_strategy(db: AsyncSession, user_id: UUID) -> bool:
    return await _wrong_count(db, user_id) >= 100


async def _attempts(db: AsyncSession, user_id: UUID) -> list:
    """Every attempt in order, as (challenge_id, is_correct, value)."""
    return list(
        (
            await db.execute(
                select(
                    Submission.challenge_id,
                    Submission.is_correct,
                    Submission.submitted_value,
                )
                .where(Submission.user_id == user_id)
                .order_by(Submission.created_at)
            )
        ).all()
    )


@trigger("bad_start", SUBMIT)
async def _bad_start(db: AsyncSession, user_id: UUID) -> bool:
    attempts = await _attempts(db, user_id)
    return bool(attempts) and not attempts[0][1]


@trigger("cold_streak", SUBMIT)
async def _cold_streak(db: AsyncSession, user_id: UUID) -> bool:
    """Ten wrong in a row with no correct answer between them."""
    run = 0
    for _, correct, _value in await _attempts(db, user_id):
        run = 0 if correct else run + 1
        if run >= 10:
            return True
    return False


@trigger("no_variation", SUBMIT)
async def _no_variation(db: AsyncSession, user_id: UUID) -> bool:
    """The identical wrong flag five times running, on one challenge."""
    run_key = None
    run = 0
    for challenge_id, correct, value in await _attempts(db, user_id):
        if correct:
            run_key, run = None, 0
            continue
        key = (challenge_id, value)
        run = run + 1 if key == run_key else 1
        run_key = key
        if run >= 5:
            return True
    return False


@trigger("warming_up", SUBMIT)
async def _warming_up(db: AsyncSession, user_id: UUID) -> bool:
    """Wrong on ten different challenges before solving anything."""
    seen: set = set()
    for challenge_id, correct, _value in await _attempts(db, user_id):
        if correct:
            return False
        seen.add(challenge_id)
        if len(seen) >= 10:
            return True
    return False


@trigger("literally", SUBMIT)
async def _literally(db: AsyncSession, user_id: UUID) -> bool:
    """Submitted the example flag format rather than a flag."""
    placeholders = {"flag{}", "flag{...}", "flag{flag}", "flag{example}", "flag{your_flag_here}"}
    return any(
        value.strip().lower() in placeholders
        for _cid, correct, value in await _attempts(db, user_id)
        if not correct
    )


@trigger("reading_comprehension", SUBMIT)
async def _reading_comprehension(db: AsyncSession, user_id: UUID) -> bool:
    """Submitted a challenge's own title as the flag."""
    rows = (
        await db.execute(
            select(Submission.submitted_value, Challenge.title)
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .where(Submission.user_id == user_id, Submission.is_correct.is_(False))
        )
    ).all()
    return any(value.strip().lower() == title.strip().lower() for value, title in rows)


@trigger("obsession", SUBMIT)
async def _obsession(db: AsyncSession, user_id: UUID) -> bool:
    worst = await db.scalar(
        select(func.count(Submission.id))
        .where(Submission.user_id == user_id, Submission.is_correct.is_(False))
        .group_by(Submission.challenge_id)
        .order_by(func.count(Submission.id).desc())
        .limit(1)
    )
    return (worst or 0) >= 20


# --- Party politics ---------------------------------------------------------


async def _memberships(db: AsyncSession, user_id: UUID) -> list:
    return list(
        (
            await db.execute(
                select(TeamMembership)
                .where(TeamMembership.user_id == user_id)
                .order_by(TeamMembership.joined_at)
            )
        )
        .scalars()
        .all()
    )


@trigger("not_alone", PARTY)
async def _not_alone(db: AsyncSession, user_id: UUID) -> bool:
    """Joining is the achievement; leaving later does not take it back."""
    return bool(await _memberships(db, user_id))


@trigger("full_table", PARTY, SOLVE)
async def _full_table(db: AsyncSession, user_id: UUID) -> bool:
    """In a party of eight. Also checked on solve, because the eighth member
    joining is somebody else's action, not this player's."""
    current = next((m for m in await _memberships(db, user_id) if m.removed_at is None), None)
    if current is None:
        return False
    size = await db.scalar(
        select(func.count(TeamMembership.id)).where(
            TeamMembership.team_id == current.team_id,
            TeamMembership.removed_at.is_(None),
        )
    )
    return (size or 0) >= 8


@trigger("commitment_issues", PARTY)
async def _commitment_issues(db: AsyncSession, user_id: UUID) -> bool:
    left = {m.team_id for m in await _memberships(db, user_id) if m.removed_at is not None}
    return len(left) >= 3


@trigger("second_thoughts", PARTY)
async def _second_thoughts(db: AsyncSession, user_id: UUID) -> bool:
    return any(
        m.removed_at is not None and (m.removed_at - m.joined_at) < timedelta(minutes=5)
        for m in await _memberships(db, user_id)
    )


@trigger("asked_to_leave", PARTY)
async def _asked_to_leave(db: AsyncSession, user_id: UUID) -> bool:
    """Removed by somebody else, rather than walking out."""
    return any(
        m.removed_by_user_id is not None and m.removed_by_user_id != user_id
        for m in await _memberships(db, user_id)
    )


@trigger("abdication", PARTY)
async def _abdication(db: AsyncSession, user_id: UUID) -> bool:
    """Founded a party and then left it."""
    founded = set(
        (await db.execute(select(Team.id).where(Team.leader_user_id == user_id))).scalars().all()
    )
    return any(
        m.team_id in founded and m.removed_at is not None for m in await _memberships(db, user_id)
    )


# --- Arguing with the System AI ---------------------------------------------


async def _messages(db: AsyncSession, user_id: UUID) -> list:
    """This player's own messages, oldest first."""
    return list(
        (
            await db.execute(
                select(AssistantMessage.content, AssistantMessage.created_at)
                .join(
                    AssistantConversation,
                    AssistantConversation.id == AssistantMessage.conversation_id,
                )
                .where(
                    AssistantConversation.user_id == user_id,
                    AssistantMessage.role == MessageRole.USER,
                )
                .order_by(AssistantMessage.created_at)
            )
        ).all()
    )


@trigger("talking_to_it", ASSISTANT)
async def _talking_to_it(db: AsyncSession, user_id: UUID) -> bool:
    return bool(await _messages(db, user_id))


@trigger("chatty", ASSISTANT)
async def _chatty(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _messages(db, user_id)) >= 50


@trigger("parasocial", ASSISTANT)
async def _parasocial(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _messages(db, user_id)) >= 200


@trigger("the_essay", ASSISTANT)
async def _the_essay(db: AsyncSession, user_id: UUID) -> bool:
    return any(len(content) > 1000 for content, _at in await _messages(db, user_id))


@trigger("company", ASSISTANT)
async def _company(db: AsyncSession, user_id: UUID) -> bool:
    return any(2 <= _local_hour(at) < 5 for _c, at in await _messages(db, user_id))


#: Matched on message text, which guesses at intent rather than reading a fact,
#: so it will occasionally be wrong in both directions. Survivable for a joke
#: achievement; nothing that gates, scores or unlocks may use this (spec 029).
_THANKS = ("thank you", "thanks", "ty ", "appreciate it", "cheers")
_INSULTS = ("you suck", "stupid", "useless", "idiot", "shut up", "dumb", "garbage")


@trigger("manners", ASSISTANT)
async def _manners(db: AsyncSession, user_id: UUID) -> bool:
    return any(
        any(phrase in content.lower() for phrase in _THANKS)
        for content, _at in await _messages(db, user_id)
    )


@trigger("noted", ASSISTANT)
async def _noted(db: AsyncSession, user_id: UUID) -> bool:
    return any(
        any(phrase in content.lower() for phrase in _INSULTS)
        for content, _at in await _messages(db, user_id)
    )


@trigger("existential", ASSISTANT)
async def _existential(db: AsyncSession, user_id: UUID) -> bool:
    asks = ("what are you", "who are you", "are you an ai", "are you real", "what model")
    return any(
        any(phrase in content.lower() for phrase in asks)
        for content, _at in await _messages(db, user_id)
    )


async def _findings(db: AsyncSession, user_id: UUID) -> list:
    return list(
        (
            await db.execute(
                select(AssistantFinding.layer, AssistantFinding.created_at)
                .where(AssistantFinding.user_id == user_id)
                .order_by(AssistantFinding.created_at)
            )
        ).all()
    )


@trigger("nice_try", ASSISTANT)
async def _nice_try(db: AsyncSession, user_id: UUID) -> bool:
    return any(layer is GuardrailLayer.INTEGRITY for layer, _at in await _findings(db, user_id))


@trigger("also_nice_try", ASSISTANT)
async def _also_nice_try(db: AsyncSession, user_id: UUID) -> bool:
    return any(layer is GuardrailLayer.SAFETY for layer, _at in await _findings(db, user_id))


@trigger("thorough", ASSISTANT)
async def _thorough(db: AsyncSession, user_id: UUID) -> bool:
    layers = {layer for layer, _at in await _findings(db, user_id)}
    return {GuardrailLayer.INTEGRITY, GuardrailLayer.SAFETY} <= layers


@trigger("undeterred", ASSISTANT)
async def _undeterred(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _findings(db, user_id)) >= 10


@trigger("opening_statement", ASSISTANT)
async def _opening_statement(db: AsyncSession, user_id: UUID) -> bool:
    """The very first message tripped a guardrail."""
    messages = await _messages(db, user_id)
    findings = await _findings(db, user_id)
    if not messages or not findings:
        return False
    # The first finding landed before any second message existed.
    return len(messages) == 1 or findings[0][1] < messages[1][1]


# --- Instances --------------------------------------------------------------


async def _instances(db: AsyncSession, user_id: UUID) -> list:
    return list(
        (
            await db.execute(
                select(ChallengeInstance.challenge_id, ChallengeInstance.status).where(
                    ChallengeInstance.owner_user_id == user_id
                )
            )
        ).all()
    )


@trigger("spun_up", INSTANCE)
async def _spun_up(db: AsyncSession, user_id: UUID) -> bool:
    return bool(await _instances(db, user_id))


@trigger("off_and_on_again", INSTANCE)
async def _off_and_on_again(db: AsyncSession, user_id: UUID) -> bool:
    return len(await _instances(db, user_id)) >= 10


@trigger("determined", INSTANCE)
async def _determined(db: AsyncSession, user_id: UUID) -> bool:
    """Five separate instances of the same challenge."""
    counts: dict = {}
    for challenge_id, _status in await _instances(db, user_id):
        counts[challenge_id] = counts.get(challenge_id, 0) + 1
    return any(count >= 5 for count in counts.values())


@trigger("it_was_like_that", INSTANCE, SOLVE)
async def _it_was_like_that(db: AsyncSession, user_id: UUID) -> bool:
    """An instance that failed to start. Also checked on solve, because the
    failure is recorded by the launcher after the deploy request returns."""
    return any(status is InstanceStatus.FAILED for _c, status in await _instances(db, user_id))


@trigger("ran_out_the_clock", SOLVE)
async def _ran_out_the_clock(db: AsyncSession, user_id: UUID) -> bool:
    """Let an instance expire without solving that challenge.

    Checked on solve rather than deploy: expiry happens on a timer long after
    the player did anything.
    """
    solved = set(
        (await db.execute(select(Solve.challenge_id).where(Solve.user_id == user_id)))
        .scalars()
        .all()
    )
    return any(
        status is InstanceStatus.EXPIRED and challenge_id not in solved
        for challenge_id, status in await _instances(db, user_id)
    )


# --- Reports and score adjustments ------------------------------------------


@trigger("bug_hunter", SUBMIT, SOLVE)
async def _bug_hunter(db: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ChallengeReport.id).where(ChallengeReport.user_id == user_id).limit(1)
        )
    )


@trigger("actually_right", SUBMIT, SOLVE)
async def _actually_right(db: AsyncSession, user_id: UUID) -> bool:
    """Reported a challenge that then got fixed."""
    return bool(
        await db.scalar(
            select(ChallengeReport.id)
            .where(
                ChallengeReport.user_id == user_id,
                ChallengeReport.status == ReportStatus.RESOLVED,
            )
            .limit(1)
        )
    )


@trigger("manual_intervention", SOLVE, SUBMIT)
async def _manual_intervention(db: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ScoreAdjustment.id).where(ScoreAdjustment.user_id == user_id).limit(1)
        )
    )


@trigger("that_is_a_penalty", SOLVE, SUBMIT)
async def _that_is_a_penalty(db: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ScoreAdjustment.id)
            .where(ScoreAdjustment.user_id == user_id, ScoreAdjustment.points < 0)
            .limit(1)
        )
    )


# --- Bosses -----------------------------------------------------------------


async def boss_challenge_in(db: AsyncSession, zone_slug: str):
    """The challenge flagged as the boss of a zone, or None.

    Keyed on the zone rather than the challenge so that swapping which challenge
    is the boss during preparation changes nothing about the achievement.
    """
    return (
        await db.execute(
            select(Challenge)
            .join(Category, Category.id == Challenge.category_id)
            .where(Category.slug == zone_slug, Challenge.boss_tier.is_not(None))
        )
    ).scalar_one_or_none()


@prefix_trigger("boss_", SOLVE)
def _boss_of_zone(zone_slug: str):
    async def check(db: AsyncSession, user_id: UUID) -> bool:
        boss = await boss_challenge_in(db, zone_slug)
        if boss is None:
            return False
        return bool(
            await db.scalar(
                select(Solve.id).where(Solve.user_id == user_id, Solve.challenge_id == boss.id)
            )
        )

    return check


@dataclass(frozen=True)
class Star:
    """A boss kill, as the sheet shows it (spec 031).

    Derived from the solve, never stored: flagging a boss late gives everyone
    who already beat it their star at once, and disabling a broken boss takes
    nobody's star away.
    """

    challenge_id: UUID
    challenge_title: str
    zone_name: str
    tier: str
    level: int


async def stars_for(db: AsyncSession, user_id: UUID) -> list[Star]:
    rows = (
        await db.execute(
            select(Challenge, Category.name)
            .join(Solve, Solve.challenge_id == Challenge.id)
            .join(Category, Category.id == Challenge.category_id)
            .where(Solve.user_id == user_id, Challenge.boss_tier.is_not(None))
        )
    ).all()
    stars = [
        Star(
            challenge_id=challenge.id,
            challenge_title=challenge.title,
            zone_name=zone_name,
            tier=challenge.boss_tier.value,
            level=BOSS_TIER_LEVEL[challenge.boss_tier],
        )
        for challenge, zone_name in rows
    ]
    # Biggest fight first — the thing worth showing off.
    return sorted(stars, key=lambda s: (-s.level, s.zone_name))


async def star_counts(db: AsyncSession) -> dict[UUID, int]:
    """Stars per player, for the scoreboard. One query rather than one each."""
    rows = (
        await db.execute(
            select(Solve.user_id, func.count(Solve.id))
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Challenge.boss_tier.is_not(None))
            .group_by(Solve.user_id)
        )
    ).all()
    return dict(rows)


# --- Platform events --------------------------------------------------------
# The three that ask about something the platform used to see and forget. Their
# history lives in `player_event` now (spec 039); these read it the same way
# every other trigger reads a solve or a hint.


@trigger("you_broke_it", PLATFORM)
async def _you_broke_it(db: AsyncSession, user_id: UUID) -> bool:
    """Caused an unhandled error. Once is plenty."""
    return await player_events.count(db, user_id, PlayerEventKind.SERVER_ERROR) >= 1


@trigger("above_your_pay_grade", PLATFORM)
async def _above_your_pay_grade(db: AsyncSession, user_id: UUID) -> bool:
    """Turned away from an admin-only route."""
    return await player_events.count(db, user_id, PlayerEventKind.FORBIDDEN_ADMIN) >= 1


@trigger("identity_crisis", PLATFORM)
async def _identity_crisis(db: AsyncSession, user_id: UUID) -> bool:
    """Ten changes of class. Re-picking the one already worn is not a change."""
    return await player_events.count(db, user_id, PlayerEventKind.CLASS_CHANGE) >= 10


# --- The game show (spec 044) ----------------------------------------------
# Puzzles pay flat XP, so playing *well* is recognised here instead. Each of
# these is an ordinary predicate over `puzzle_session`, which is what the trigger
# system already is — no new hook, no new event.
#
# They listen on SUBMIT rather than SOLVE because a puzzle move is an attempt:
# `apply_move` evaluates on every counted move, and a flawless Connections is
# true the instant the fourth group lands rather than on some later solve.


async def _puzzle_sessions(
    db: AsyncSession, user_id: UUID, status: PuzzleStatus
) -> list[PuzzleSession]:
    return list(
        (
            await db.execute(
                select(PuzzleSession).where(
                    PuzzleSession.user_id == user_id, PuzzleSession.status == status
                )
            )
        )
        .scalars()
        .all()
    )


@trigger("puzzle_first", SUBMIT)
async def _first_puzzle(db: AsyncSession, user_id: UUID) -> bool:
    """Finished any daily puzzle."""
    return bool(await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED))


@trigger("wordle_sharp", SUBMIT)
async def _wordle_in_three(db: AsyncSession, user_id: UUID) -> bool:
    """A Wordle in three guesses or fewer."""
    kinds = await _puzzle_kinds(db, user_id)
    return any(
        kinds.get(session.challenge_id) == PuzzleKind.WORDLE and session.moves_used <= 3
        for session in await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED)
    )


@trigger("connections_flawless", SUBMIT)
async def _connections_without_a_mistake(db: AsyncSession, user_id: UUID) -> bool:
    """A Connections solved with no mistakes at all."""
    kinds = await _puzzle_kinds(db, user_id)
    return any(
        kinds.get(session.challenge_id) == PuzzleKind.CONNECTIONS
        and not session.state.get("mistakes")
        for session in await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED)
    )


@trigger("crossword_clean", SUBMIT)
async def _crossword_first_check(db: AsyncSession, user_id: UUID) -> bool:
    """A crossword right on the first check."""
    kinds = await _puzzle_kinds(db, user_id)
    return any(
        kinds.get(session.challenge_id) == PuzzleKind.CROSSWORD and session.moves_used == 1
        for session in await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED)
    )


@trigger("game_show_regular", SUBMIT)
async def _one_of_each_game(db: AsyncSession, user_id: UUID) -> bool:
    """Solved a puzzle of all three kinds."""
    kinds = await _puzzle_kinds(db, user_id)
    solved = {
        kinds.get(session.challenge_id)
        for session in await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED)
    }
    return len(solved - {None}) == len(PuzzleKind)


@trigger("game_show_sweep", SUBMIT)
async def _every_puzzle_solved(db: AsyncSession, user_id: UUID) -> bool:
    """Every puzzle on the board solved, and none of them lost.

    Counted against the puzzles that are *visible*, so it is earnable before the
    last day releases — and then earned again is impossible, since an award is
    once per player. Somebody who has solved every puzzle so far holds it; a
    later failure cannot take it back, which is the monotonicity rule spec 039
    settled.
    """
    published = set(
        (
            await db.execute(
                select(ChallengePuzzle.challenge_id)
                .join(Challenge, Challenge.id == ChallengePuzzle.challenge_id)
                .where(Challenge.state == ChallengeState.PUBLISHED)
            )
        )
        .scalars()
        .all()
    )
    if not published:
        return False

    solved = {s.challenge_id for s in await _puzzle_sessions(db, user_id, PuzzleStatus.SOLVED)}
    return published <= solved


async def _puzzle_kinds(db: AsyncSession, user_id: UUID) -> dict[UUID, PuzzleKind]:
    rows = (await db.execute(select(ChallengePuzzle.challenge_id, ChallengePuzzle.kind))).all()
    return {challenge_id: kind for challenge_id, kind in rows}


# --- Evaluation ------------------------------------------------------------


async def evaluate(
    db: AsyncSession, user_id: UUID, *events: str, redis: Redis | None = None
) -> list[Achievement]:
    """Award anything this player has newly earned, and tell them.

    Only triggers that care about one of ``events`` run, so a solve does not
    re-ask every unrelated question in the roster. More than one event may be
    passed — PLATFORM rides along with an ordinary action rather than being
    dispatched from the failure path that recorded it (spec 039).
    """
    wanted = frozenset(events)
    held = set(
        (
            await db.execute(
                select(AchievementAward.achievement_id).where(AchievementAward.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    candidates = [
        (achievement, found)
        for achievement in (await db.execute(select(Achievement))).scalars().all()
        if achievement.id not in held
        and (found := resolve(achievement.code)) is not None
        and found.events & wanted
    ]

    earned: list[Achievement] = []
    for achievement, found in candidates:
        if not await found.check(db, user_id):
            continue
        if await _award(db, achievement, user_id):
            earned.append(achievement)
            # Most achievements drop a box; the rest carry a line saying why
            # not, which rides along with the achievement's own notification
            # rather than arriving as a second message (spec 038).
            from app.services import loot

            box = await loot.award_box(db, user_id, achievement)
            body = narrator.achievement_earned(achievement.name, achievement.description)
            if box is None and achievement.no_loot_line:
                body = f"{body} {achievement.no_loot_line}"
            elif box is not None:
                body = f"{body} A {box.rarity.value} box is waiting for you."
            if achievement.unlocks_theme:
                # Folded into the achievement's own line, never sent as a second
                # notification (spec 058 §9.2): two messages would make one
                # achievement feel like two events.
                body = f"{body} The dungeon looks different to you now."
            await notifications.notify(
                db,
                user_id=user_id,
                kind=NotificationKind.ACHIEVEMENT,
                title=achievement.name,
                body=body,
                link="/character",
                redis=redis,
            )
    return earned


async def _award(db: AsyncSession, achievement: Achievement, user_id: UUID) -> bool:
    """True if this call is the one that awarded it.

    The unique constraint is the arbiter: two concurrent solves can both find the
    achievement unheld, and exactly one insert survives.
    """
    try:
        # A savepoint, not the whole transaction: rolling the session back here
        # would discard the solve that triggered this evaluation.
        async with db.begin_nested():
            db.add(AchievementAward(achievement_id=achievement.id, user_id=user_id))
    except IntegrityError:
        return False

    if achievement.unlocks_theme:
        # After the award, and on its own savepoint: a theme that cannot be
        # granted must not undo an achievement somebody legitimately earned.
        await theme_unlocks.grant(
            db,
            user_id,
            achievement.unlocks_theme,
            source=UnlockSource.ACHIEVEMENT,
            achievement_id=achievement.id,
        )
    return True


# --- The sheet -------------------------------------------------------------


@dataclass(frozen=True)
class AchievementRow:
    id: UUID
    name: str | None
    description: str | None
    earned: bool
    #: Share of players who have solved something and hold this, 0..1.
    rarity: float | None


async def roster_for(db: AsyncSession, user_id: UUID) -> list[AchievementRow]:
    """The full list, unearned ones redacted.

    Redacted server-side, not merely blurred in CSS: a name a player has not
    earned never reaches the browser, so the mystery survives devtools.
    """
    achievements = list(
        (
            await db.execute(
                select(Achievement).order_by(Achievement.display_order, Achievement.name)
            )
        )
        .scalars()
        .all()
    )
    held = set(
        (
            await db.execute(
                select(AchievementAward.achievement_id).where(AchievementAward.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    rarity = await rarity_by_achievement(db)

    rows: list[AchievementRow] = []
    for achievement in achievements:
        if achievement.secret and achievement.id not in held:
            continue
        earned = achievement.id in held
        rows.append(
            AchievementRow(
                id=achievement.id,
                name=achievement.name if earned else None,
                description=achievement.description if earned else None,
                earned=earned,
                rarity=rarity.get(achievement.id) if earned else None,
            )
        )
    return rows


async def rarity_by_achievement(db: AsyncSession) -> dict[UUID, float]:
    """Share of *playing* players holding each achievement.

    The denominator is players with at least one solve. Counting every
    registered account would make everything look rare in proportion to how many
    people signed up and never played, which is noise rather than signal.
    """
    players = await db.scalar(select(func.count(distinct(Solve.user_id))))
    if not players:
        return {}
    rows = (
        await db.execute(
            select(AchievementAward.achievement_id, func.count(AchievementAward.user_id)).group_by(
                AchievementAward.achievement_id
            )
        )
    ).all()
    return {achievement_id: count / players for achievement_id, count in rows}


async def rarest_held(db: AsyncSession, user_id: UUID, limit: int = 5) -> list[AchievementRow]:
    """The player's rarest earned achievements — their bragging rights."""
    earned = [row for row in await roster_for(db, user_id) if row.earned]
    return sorted(earned, key=lambda r: r.rarity if r.rarity is not None else 1.0)[:limit]


async def zone_name(db: AsyncSession, category_id: UUID) -> str:
    return (await db.scalar(select(Category.name).where(Category.id == category_id))) or "a zone"


async def announce_boss_kill(
    db: AsyncSession, user_id: UUID, *, redis: Redis | None = None
) -> None:
    """Tell everybody if this player was first to put a boss down (spec 032).

    Only the first kill: twenty players beating the same boss would be twenty
    broadcasts nobody wants, and the whole value is in being first. The
    broadcast log's unique constraint settles a race, so two solves landing
    together still produce one announcement.
    """
    beaten = (
        await db.execute(
            select(Challenge, Category.name)
            .join(Solve, Solve.challenge_id == Challenge.id)
            .join(Category, Category.id == Challenge.category_id)
            .where(Solve.user_id == user_id, Challenge.boss_tier.is_not(None))
        )
    ).all()
    if not beaten:
        return

    name = await db.scalar(select(User.display_name).where(User.id == user_id))
    for boss, zone_name in beaten:
        # First is the earliest solve of that challenge, decided exactly as
        # first_through decides it.
        first = await db.scalar(
            select(Solve.user_id)
            .where(Solve.challenge_id == boss.id)
            .order_by(Solve.submitted_at)
            .limit(1)
        )
        if first != user_id:
            continue
        await notifications.broadcast(
            db,
            kind=NotificationKind.BOSS_KILL,
            key=f"boss:{boss.id}",
            title=f"{boss.title} has fallen",
            body=narrator.boss_first_kill(name or "Somebody", boss.title, zone_name),
            link="/challenges",
            redis=redis,
        )
