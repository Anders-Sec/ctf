"""Listing, searching and filtering challenges for the admin manager (spec 041).

The old listing was written for a handful of challenges: select everything, sort
by title, hand it over. The event has 242, and at that size the questions change.
An admin does not ask "where is *Airmail*" so much as "what is still not
finished" — which challenge has no flag, which zone has no boss, which wing is
still in draft.

So the filtering happens here rather than in the browser. That is also what lets
spec 042 offer "select every row this filter found": the server decides the set,
and the client does not have to hold all 242 to reason about them.

The counts are the other half. Flags, hints and skills per challenge are three
aggregates, and doing them per row is the N+1 that shows up at 242 and nowhere
else — see :func:`_counts`.
"""

import enum
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.challenge import (
    BossTier,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    Difficulty,
    UnlockRequirement,
    points_for,
)
from app.models.hint import Hint
from app.models.skill import ChallengeSkill


class Problem(enum.StrEnum):
    """The canned "what is not finished" queries (spec 041 §4).

    Named rather than expressed as a filter grammar: these are the handful of
    questions actually asked while building an event, and a grammar would be a
    lot of surface for a set that fits on one hand.
    """

    #: Nobody can solve it.
    NO_FLAG = "no_flag"
    #: Its XP lands nowhere on a character sheet.
    NO_SKILLS = "no_skills"
    #: A title and nothing else.
    NO_DESCRIPTION = "no_description"
    NO_HINTS = "no_hints"
    DRAFT = "draft"
    #: Every challenge in a zone that has no boss (spec 031).
    ZONE_HAS_NO_BOSS = "zone_has_no_boss"
    #: XP differs from what its difficulty suggests. Not a fault — spec 040 made
    #: that deliberate — but the one view that makes a generated file reviewable.
    XP_DIFFERS_FROM_DIFFICULTY = "xp_differs_from_difficulty"


class Sort(enum.StrEnum):
    TITLE = "title"
    XP = "xp"
    DIFFICULTY = "difficulty"
    SOLVES = "solves"
    STATE = "state"


@dataclass(frozen=True)
class ChallengeFilters:
    search: str | None = None
    category_id: UUID | None = None
    state: ChallengeState | None = None
    difficulty: Difficulty | None = None
    boss_tier: BossTier | None = None
    #: True for any boss, False for none, None for "do not care".
    is_boss: bool | None = None
    has_container: bool | None = None
    problem: Problem | None = None
    sort: Sort = Sort.TITLE


@dataclass
class Counts:
    answers: dict[UUID, int]
    hints: dict[UUID, int]
    skills: dict[UUID, int]
    prerequisites: dict[UUID, int]


async def list_challenges(
    db: AsyncSession, filters: ChallengeFilters
) -> tuple[list[Challenge], Counts]:
    """The filtered set, and the counts for exactly those rows."""
    stmt = select(Challenge).options(selectinload(Challenge.category))
    stmt = _apply_filters(stmt, filters)
    stmt = _apply_sort(stmt, filters.sort)

    challenges = list((await db.execute(stmt)).scalars().all())
    return challenges, await _counts(db, [c.id for c in challenges])


def _apply_filters(stmt: Select, filters: ChallengeFilters) -> Select:
    if filters.search:
        # Title, slug and body — never the answer values. A search box that
        # matches flags is a search box that puts them on screen next to a
        # screenshot, and an admin looking for one has the drawer.
        pattern = f"%{filters.search.strip()}%"
        stmt = stmt.where(
            or_(
                Challenge.title.ilike(pattern),
                Challenge.slug.ilike(pattern),
                Challenge.body.ilike(pattern),
            )
        )
    if filters.category_id is not None:
        stmt = stmt.where(Challenge.category_id == filters.category_id)
    if filters.state is not None:
        stmt = stmt.where(Challenge.state == filters.state)
    if filters.difficulty is not None:
        stmt = stmt.where(Challenge.difficulty == filters.difficulty)
    if filters.boss_tier is not None:
        stmt = stmt.where(Challenge.boss_tier == filters.boss_tier)
    if filters.is_boss is not None:
        stmt = stmt.where(
            Challenge.boss_tier.is_not(None) if filters.is_boss else Challenge.boss_tier.is_(None)
        )
    if filters.has_container is not None:
        stmt = stmt.where(
            Challenge.container_template_id.is_not(None)
            if filters.has_container
            else Challenge.container_template_id.is_(None)
        )
    if filters.problem is not None:
        stmt = _apply_problem(stmt, filters.problem)
    return stmt


def _apply_problem(stmt: Select, problem: Problem) -> Select:
    if problem is Problem.NO_FLAG:
        return stmt.where(
            ~select(ChallengeAnswer.id).where(ChallengeAnswer.challenge_id == Challenge.id).exists()
        )
    if problem is Problem.NO_SKILLS:
        return stmt.where(
            ~select(ChallengeSkill.challenge_id)
            .where(ChallengeSkill.challenge_id == Challenge.id)
            .exists()
        )
    if problem is Problem.NO_HINTS:
        return stmt.where(~select(Hint.id).where(Hint.challenge_id == Challenge.id).exists())
    if problem is Problem.NO_DESCRIPTION:
        # Whitespace counts as empty: a body of one space is not a description.
        return stmt.where(func.coalesce(func.trim(Challenge.body), "") == "")
    if problem is Problem.DRAFT:
        return stmt.where(Challenge.state == ChallengeState.DRAFT)
    if problem is Problem.ZONE_HAS_NO_BOSS:
        # Every challenge in a zone that holds no boss, so the result is
        # actionable — it names the candidates, not the empty zone.
        bossed = (
            select(Challenge.category_id).where(Challenge.boss_tier.is_not(None)).scalar_subquery()
        )
        return stmt.where(Challenge.category_id.not_in(bossed))
    if problem is Problem.XP_DIFFERS_FROM_DIFFICULTY:
        xp_base = get_settings().xp_base
        # One OR per tier rather than a CASE: six members, and this reads.
        return stmt.where(
            or_(
                *(
                    (Challenge.difficulty == difficulty)
                    & (Challenge.initial_points != points_for(difficulty, xp_base))
                    for difficulty in Difficulty
                )
            )
        )
    return stmt


def _apply_sort(stmt: Select, sort: Sort) -> Select:
    if sort is Sort.XP:
        return stmt.order_by(Challenge.initial_points.desc(), Challenge.title)
    if sort is Sort.DIFFICULTY:
        return stmt.order_by(Challenge.difficulty, Challenge.title)
    if sort is Sort.STATE:
        return stmt.order_by(Challenge.state, Challenge.title)
    # Solves are counted separately and sorted by the caller; ordering by title
    # here keeps the fallback stable.
    return stmt.order_by(Challenge.title)


async def _counts(db: AsyncSession, challenge_ids: list[UUID]) -> Counts:
    """Four aggregates in four queries, not four per row.

    The listing this replaces reported ``answer_count`` as
    ``len(c.answers) if "answers" in c.__dict__ else 0``. ``Challenge.answers``
    is ``lazy="raise"`` and was never eager-loaded, so that guard never passed
    and the count was **always zero** — for every challenge, since the listing
    shipped. Nothing rendered it, so nothing complained.
    """
    if not challenge_ids:
        return Counts({}, {}, {}, {})

    async def group(column, table) -> dict[UUID, int]:
        rows = await db.execute(
            select(column, func.count()).where(column.in_(challenge_ids)).group_by(column)
        )
        return dict(rows.all())

    return Counts(
        answers=await group(ChallengeAnswer.challenge_id, ChallengeAnswer),
        hints=await group(Hint.challenge_id, Hint),
        skills=await group(ChallengeSkill.challenge_id, ChallengeSkill),
        prerequisites=await group(UnlockRequirement.challenge_id, UnlockRequirement),
    )


@dataclass
class ZoneSummary:
    """What a zone's header row says (spec 041 §3)."""

    category_id: UUID
    name: str
    slug: str
    display_order: int
    challenge_count: int
    total_xp: int
    #: The challenge holding the zone's boss slot, or None. One per zone.
    boss_challenge_id: UUID | None
    boss_tier: BossTier | None
    draft_count: int
    published_count: int


async def zone_summaries(db: AsyncSession) -> list[ZoneSummary]:
    """One grouped query rather than the client summing a list it may only hold
    a filtered slice of.

    The XP total is the point. Spec 040 moved XP onto the challenge, so a zone can
    now drift off the 1,900 the level curve was tuned against and nothing
    complains. This is where that becomes visible.
    """
    rows = (
        await db.execute(
            select(
                Category.id,
                Category.name,
                Category.slug,
                Category.display_order,
                func.count(Challenge.id),
                func.coalesce(func.sum(Challenge.initial_points), 0),
                func.count(Challenge.id).filter(Challenge.state == ChallengeState.DRAFT),
                func.count(Challenge.id).filter(Challenge.state == ChallengeState.PUBLISHED),
            )
            .outerjoin(Challenge, Challenge.category_id == Category.id)
            .group_by(Category.id)
            .order_by(Category.display_order, Category.name)
        )
    ).all()

    bosses = {
        category_id: (challenge_id, tier)
        for category_id, challenge_id, tier in (
            await db.execute(
                select(Challenge.category_id, Challenge.id, Challenge.boss_tier).where(
                    Challenge.boss_tier.is_not(None)
                )
            )
        ).all()
    }

    return [
        ZoneSummary(
            category_id=category_id,
            name=name,
            slug=slug,
            display_order=display_order,
            challenge_count=count,
            total_xp=int(total_xp),
            boss_challenge_id=bosses.get(category_id, (None, None))[0],
            boss_tier=bosses.get(category_id, (None, None))[1],
            draft_count=drafts,
            published_count=published,
        )
        for (
            category_id,
            name,
            slug,
            display_order,
            count,
            total_xp,
            drafts,
            published,
        ) in rows
    ]
