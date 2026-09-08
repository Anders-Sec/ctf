"""Evaluating unlock requirements (spec 017).

One table gates two things — a challenge or a zone (category) — so one evaluator
answers both. Everything here is per-player: given some requirement rows, which
are met, and what should the player be told about the ones that are not.

The gate types read different columns:

===================== ===========================================
``challenge_solved``  ``required_challenge_id``
``min_xp``            ``threshold`` against banked XP (spec 015)
``skill_level``       ``required_skill_id`` + ``threshold``
``solves_in_category`` ``required_category_id`` + ``threshold``
===================== ===========================================

Locking considers *every* requirement; the player-facing hint lists only the ones
they are allowed to see, so a locked challenge never reveals a hidden one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, NotFoundError
from app.models.challenge import (
    Category,
    Challenge,
    ChallengeState,
    RequirementType,
    UnlockRequirement,
)
from app.models.play import Solve
from app.models.skill import Skill
from app.services import scoring


class InvalidRequirement(AppError):
    status_code = 409
    code = "invalid_requirement"
    message = "That requirement is not valid."


#: The states in which a player may see a challenge at all.
PLAYER_VISIBLE = (ChallengeState.LOCKED, ChallengeState.PUBLISHED)


@dataclass(frozen=True)
class RequirementView:
    """One requirement, as the player should read it.

    ``description`` is pre-rendered so a client can show any gate type without a
    per-type branch, and ``progress`` is what the player currently has, so a shut
    room can say "320 / 500".
    """

    type: RequirementType
    met: bool
    description: str
    challenge_id: UUID | None = None
    title: str | None = None
    skill_id: UUID | None = None
    skill_name: str | None = None
    category_id: UUID | None = None
    category_name: str | None = None
    threshold: int | None = None
    progress: int | None = None


@dataclass(frozen=True)
class GateStatus:
    #: True when the player has NOT met every requirement.
    locked: bool
    #: Only the requirements the player is allowed to see.
    visible_requirements: list[RequirementView]


@dataclass
class PlayerProgress:
    """What the player has, loaded once for a batch of requirements.

    Each piece is fetched only if some requirement actually asks for it — a board
    with no XP gates does not pay for an XP query.
    """

    solved_challenge_ids: set[UUID]
    total_xp: int
    player_level: int
    skill_levels: dict[UUID, int]
    solves_per_category: dict[UUID, int]
    #: (solved, visible) per category — the numerator and denominator of a
    #: percentage gate. Visible only, so unreleased content cannot make a gate
    #: unreachable, and hiding a challenge can only help.
    category_progress: dict[UUID, tuple[int, int]]


async def load_progress(
    db: AsyncSession,
    user_id: UUID,
    requirements: list[UnlockRequirement],
    now: datetime | None = None,
) -> PlayerProgress:
    now = now or datetime.now(UTC)
    types = {req.requirement_type for req in requirements}

    solved: set[UUID] = set()
    if RequirementType.CHALLENGE_SOLVED in types:
        needed = {r.required_challenge_id for r in requirements if r.required_challenge_id}
        if needed:
            solved = set(
                (
                    await db.execute(
                        select(Solve.challenge_id).where(
                            Solve.user_id == user_id, Solve.challenge_id.in_(needed)
                        )
                    )
                )
                .scalars()
                .all()
            )

    total_xp = 0
    player_level = 1
    if types & {RequirementType.MIN_XP, RequirementType.PLAYER_LEVEL}:
        total_xp = await scoring.total_xp(db, user_id)
        player_level = scoring.level_for_xp(total_xp)

    skill_levels: dict[UUID, int] = {}
    if RequirementType.SKILL_LEVEL in types:
        by_skill = await scoring.skill_xp_for_user(db, user_id)
        skill_levels = {skill_id: scoring.skill_level(xp) for skill_id, xp in by_skill.items()}

    per_category: dict[UUID, int] = {}
    if RequirementType.SOLVES_IN_CATEGORY in types:
        rows = await db.execute(
            select(Challenge.category_id, func.count())
            .select_from(Solve)
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Solve.user_id == user_id)
            .group_by(Challenge.category_id)
        )
        per_category = {category_id: count for category_id, count in rows}

    progress_by_category: dict[UUID, tuple[int, int]] = {}
    if RequirementType.PERCENT_IN_CATEGORY in types:
        wanted = {r.required_category_id for r in requirements if r.required_category_id}
        if wanted:
            progress_by_category = await _category_progress(db, user_id, wanted, now)

    return PlayerProgress(
        solved_challenge_ids=solved,
        total_xp=total_xp,
        player_level=player_level,
        skill_levels=skill_levels,
        solves_per_category=per_category,
        category_progress=progress_by_category,
    )


async def _category_progress(
    db: AsyncSession, user_id: UUID, category_ids: set[UUID], now: datetime
) -> dict[UUID, tuple[int, int]]:
    """Solved and visible counts per category, for percentage gates.

    Visibility is evaluated the same way the board does it, so a draft or
    unreleased challenge is in neither the numerator nor the denominator.
    """
    rows = (
        (
            await db.execute(
                select(Challenge).where(
                    Challenge.category_id.in_(category_ids),
                    Challenge.state != ChallengeState.DRAFT,
                )
            )
        )
        .scalars()
        .all()
    )
    visible = [c for c in rows if c.effective_state(now) in PLAYER_VISIBLE]
    if not visible:
        return {category_id: (0, 0) for category_id in category_ids}

    solved_ids = set(
        (
            await db.execute(
                select(Solve.challenge_id).where(
                    Solve.user_id == user_id,
                    Solve.challenge_id.in_([c.id for c in visible]),
                )
            )
        )
        .scalars()
        .all()
    )

    totals: dict[UUID, tuple[int, int]] = {category_id: (0, 0) for category_id in category_ids}
    for challenge in visible:
        done, total = totals.get(challenge.category_id, (0, 0))
        totals[challenge.category_id] = (
            done + (1 if challenge.id in solved_ids else 0),
            total + 1,
        )
    return totals


async def _label_lookups(
    db: AsyncSession, requirements: list[UnlockRequirement]
) -> tuple[dict[UUID, Challenge], dict[UUID, str], dict[UUID, str]]:
    """Titles and names for the requirement hints, in three batched queries."""
    challenge_ids = {r.required_challenge_id for r in requirements if r.required_challenge_id}
    skill_ids = {r.required_skill_id for r in requirements if r.required_skill_id}
    category_ids = {r.required_category_id for r in requirements if r.required_category_id}

    challenges: dict[UUID, Challenge] = {}
    if challenge_ids:
        rows = (
            (await db.execute(select(Challenge).where(Challenge.id.in_(challenge_ids))))
            .scalars()
            .all()
        )
        challenges = {c.id: c for c in rows}

    skills: dict[UUID, str] = {}
    if skill_ids:
        rows = await db.execute(select(Skill.id, Skill.name).where(Skill.id.in_(skill_ids)))
        skills = {skill_id: name for skill_id, name in rows.all()}

    categories: dict[UUID, str] = {}
    if category_ids:
        rows = await db.execute(
            select(Category.id, Category.name).where(Category.id.in_(category_ids))
        )
        categories = {category_id: name for category_id, name in rows.all()}

    return challenges, skills, categories


def _evaluate(
    requirement: UnlockRequirement,
    progress: PlayerProgress,
    challenges: dict[UUID, Challenge],
    skills: dict[UUID, str],
    categories: dict[UUID, str],
) -> RequirementView:
    kind = requirement.requirement_type
    threshold = requirement.threshold or 0

    if kind == RequirementType.CHALLENGE_SOLVED:
        required = challenges.get(requirement.required_challenge_id)  # type: ignore[arg-type]
        title = required.title if required else "a challenge"
        met = requirement.required_challenge_id in progress.solved_challenge_ids
        return RequirementView(
            type=kind,
            met=met,
            description=f"Solve {title}",
            challenge_id=requirement.required_challenge_id,
            title=title,
        )

    if kind == RequirementType.MIN_XP:
        return RequirementView(
            type=kind,
            met=progress.total_xp >= threshold,
            description=f"Reach {threshold} XP",
            threshold=threshold,
            progress=progress.total_xp,
        )

    if kind == RequirementType.SKILL_LEVEL:
        skill_id = requirement.required_skill_id
        # An undiscovered skill keeps its name (spec 018): a locked challenge must
        # not be the thing that reveals a rare skill exists.
        level = progress.skill_levels.get(skill_id, 0) if skill_id else 0
        name = (
            skills.get(skill_id, "a skill") if skill_id and level > 0 else "an undiscovered skill"
        )
        return RequirementView(
            type=kind,
            met=level >= threshold,
            description=f"{name} level {threshold}",
            skill_id=skill_id,
            skill_name=name,
            threshold=threshold,
            progress=level,
        )

    if kind == RequirementType.SOLVES_IN_CATEGORY:
        category_id = requirement.required_category_id
        name = categories.get(category_id, "a category") if category_id else "a category"
        count = progress.solves_per_category.get(category_id, 0) if category_id else 0
        return RequirementView(
            type=kind,
            met=count >= threshold,
            description=f"Clear {threshold} in {name}",
            category_id=category_id,
            category_name=name,
            threshold=threshold,
            progress=count,
        )

    if kind == RequirementType.PERCENT_IN_CATEGORY:
        category_id = requirement.required_category_id
        name = categories.get(category_id, "a zone") if category_id else "a zone"
        done, total = progress.category_progress.get(category_id, (0, 0)) if category_id else (0, 0)
        # No visible challenges means nothing to clear, so the gate cannot be
        # met — better an unopenable zone than one that opens for free.
        percent = int(done * 100 / total) if total else 0
        return RequirementView(
            type=kind,
            met=total > 0 and percent >= threshold,
            description=f"Clear {threshold}% of {name}",
            category_id=category_id,
            category_name=name,
            threshold=threshold,
            progress=percent,
        )

    if kind == RequirementType.PLAYER_LEVEL:
        return RequirementView(
            type=kind,
            met=progress.player_level >= threshold,
            description=f"Reach level {threshold}",
            threshold=threshold,
            progress=progress.player_level,
        )

    # Unreachable while RequirementType is exhaustive above, but a new member
    # should fail closed rather than silently unlocking everything.
    return RequirementView(type=kind, met=False, description="Unknown requirement")


def _is_visible(view: RequirementView, challenges: dict[UUID, Challenge], now: datetime) -> bool:
    """Value gates are always safe to show; a challenge gate only if that
    challenge is one the player could see anyway."""
    if view.type != RequirementType.CHALLENGE_SOLVED:
        return True
    required = challenges.get(view.challenge_id) if view.challenge_id else None
    return required is not None and required.effective_state(now) in PLAYER_VISIBLE


async def evaluate_groups(
    db: AsyncSession,
    user_id: UUID,
    requirements: list[UnlockRequirement],
    now: datetime,
    key: str = "challenge_id",
) -> dict[UUID, GateStatus]:
    """Group requirements by their target and evaluate each group.

    ``key`` selects the target column — ``challenge_id`` for challenge gates,
    ``category_id`` for zone gates.
    """
    if not requirements:
        return {}

    progress = await load_progress(db, user_id, requirements, now)
    challenges, skills, categories = await _label_lookups(db, requirements)

    grouped: dict[UUID, list[UnlockRequirement]] = {}
    for requirement in requirements:
        target = getattr(requirement, key)
        if target is not None:
            grouped.setdefault(target, []).append(requirement)

    result: dict[UUID, GateStatus] = {}
    for target, group in grouped.items():
        views = [_evaluate(r, progress, challenges, skills, categories) for r in group]
        result[target] = GateStatus(
            locked=not all(v.met for v in views),
            visible_requirements=[v for v in views if _is_visible(v, challenges, now)],
        )
    return result


# ---------------------------------------------------------------------------
# Admin: creating and removing requirements
# ---------------------------------------------------------------------------

#: Which columns each gate type requires. Validation is a table, not a pile of
#: ifs, so adding a type means adding a row.
_REQUIRED_FIELDS: dict[RequirementType, tuple[str, ...]] = {
    RequirementType.CHALLENGE_SOLVED: ("required_challenge_id",),
    RequirementType.MIN_XP: ("threshold",),
    RequirementType.SKILL_LEVEL: ("required_skill_id", "threshold"),
    RequirementType.SOLVES_IN_CATEGORY: ("required_category_id", "threshold"),
    RequirementType.PERCENT_IN_CATEGORY: ("required_category_id", "threshold"),
    RequirementType.PLAYER_LEVEL: ("threshold",),
}

_ALL_FIELDS = ("required_challenge_id", "required_skill_id", "required_category_id", "threshold")


async def add_requirement(
    db: AsyncSession,
    *,
    challenge_id: UUID | None = None,
    category_id: UUID | None = None,
    requirement_type: RequirementType,
    required_challenge_id: UUID | None = None,
    required_skill_id: UUID | None = None,
    required_category_id: UUID | None = None,
    threshold: int | None = None,
) -> UnlockRequirement:
    """Gate a challenge or a zone. Idempotent on an identical requirement."""
    if (challenge_id is None) == (category_id is None):
        raise InvalidRequirement(
            "A requirement gates exactly one challenge or one category.",
            code="requirement_target",
        )

    values = {
        "required_challenge_id": required_challenge_id,
        "required_skill_id": required_skill_id,
        "required_category_id": required_category_id,
        "threshold": threshold,
    }
    needed = _REQUIRED_FIELDS[requirement_type]
    for field in needed:
        if values[field] is None:
            raise InvalidRequirement(
                f"A {requirement_type.value} requirement needs {field}.",
                code="requirement_fields",
            )
    # Fail loudly on fields that do not belong to this type, rather than storing
    # something that will silently never be read.
    for field in _ALL_FIELDS:
        if field not in needed and values[field] is not None:
            raise InvalidRequirement(
                f"A {requirement_type.value} requirement does not take {field}.",
                code="requirement_fields",
            )

    if threshold is not None and threshold < 1:
        raise InvalidRequirement("A threshold must be at least 1.", code="requirement_fields")
    if requirement_type == RequirementType.PERCENT_IN_CATEGORY and threshold > 100:
        raise InvalidRequirement("A percentage cannot exceed 100.", code="requirement_fields")

    await _check_targets_exist(db, values)

    # challenge_solved on a challenge is 014's prerequisite edge, cycles and all.
    if requirement_type == RequirementType.CHALLENGE_SOLVED and challenge_id is not None:
        from app.services import challenges as challenge_service

        await challenge_service.add_prerequisite(db, challenge_id, required_challenge_id)
        existing = await db.scalar(
            select(UnlockRequirement).where(
                UnlockRequirement.challenge_id == challenge_id,
                UnlockRequirement.required_challenge_id == required_challenge_id,
            )
        )
        return existing

    duplicate = await db.scalar(
        select(UnlockRequirement).where(
            UnlockRequirement.challenge_id == challenge_id,
            UnlockRequirement.category_id == category_id,
            UnlockRequirement.requirement_type == requirement_type,
            UnlockRequirement.required_challenge_id == required_challenge_id,
            UnlockRequirement.required_skill_id == required_skill_id,
            UnlockRequirement.required_category_id == required_category_id,
        )
    )
    if duplicate is not None:
        duplicate.threshold = threshold
        await db.flush()
        return duplicate

    requirement = UnlockRequirement(
        challenge_id=challenge_id,
        category_id=category_id,
        requirement_type=requirement_type,
        required_challenge_id=required_challenge_id,
        required_skill_id=required_skill_id,
        required_category_id=required_category_id,
        threshold=threshold,
    )
    db.add(requirement)
    await db.flush()
    return requirement


async def _check_targets_exist(db: AsyncSession, values: dict) -> None:
    """Every referenced row must exist, so a gate can never be unsatisfiable."""
    lookups = (
        ("required_challenge_id", Challenge, "No such challenge."),
        ("required_skill_id", Skill, "No such skill."),
        ("required_category_id", Category, "No such category."),
    )
    for field, model, message in lookups:
        target_id = values[field]
        if target_id is None:
            continue
        if await db.scalar(select(model.id).where(model.id == target_id)) is None:
            raise NotFoundError(message)


async def remove_requirement(db: AsyncSession, requirement_id: UUID) -> None:
    await db.execute(sql_delete(UnlockRequirement).where(UnlockRequirement.id == requirement_id))
    await db.flush()


async def list_requirements(
    db: AsyncSession, *, challenge_id: UUID | None = None, category_id: UUID | None = None
) -> list[UnlockRequirement]:
    stmt = select(UnlockRequirement)
    if challenge_id is not None:
        stmt = stmt.where(UnlockRequirement.challenge_id == challenge_id)
    else:
        stmt = stmt.where(UnlockRequirement.category_id == category_id)
    return list((await db.execute(stmt)).scalars().all())


async def describe(
    db: AsyncSession, user_id: UUID, requirements: list[UnlockRequirement], now: datetime
) -> list[RequirementView]:
    """Evaluate a flat list of requirements for one player, unGrouped."""
    if not requirements:
        return []
    progress = await load_progress(db, user_id, requirements, now)
    challenges, skills, categories = await _label_lookups(db, requirements)
    return [_evaluate(r, progress, challenges, skills, categories) for r in requirements]


async def evaluate_for_challenges(
    db: AsyncSession, user_id: UUID, challenge_ids: list[UUID], now: datetime
) -> dict[UUID, GateStatus]:
    """Whether each challenge is locked, counting **its zone's** gates too.

    A challenge is unlocked iff its own requirements are met *and* its category's
    are (spec 017). Both sets are evaluated in one batch and merged, so a zone gate
    reads to the player as just another reason the room is shut — and because this
    is what ``prerequisite_status`` returns, the lock applies to submission, not
    only to display.
    """
    if not challenge_ids:
        return {}

    pairs = (
        await db.execute(
            select(Challenge.id, Challenge.category_id).where(Challenge.id.in_(challenge_ids))
        )
    ).all()
    challenge_to_category = {challenge_id: category_id for challenge_id, category_id in pairs}
    category_ids = {c for c in challenge_to_category.values() if c is not None}

    requirements = (
        (
            await db.execute(
                select(UnlockRequirement).where(
                    or_(
                        UnlockRequirement.challenge_id.in_(challenge_ids),
                        UnlockRequirement.category_id.in_(category_ids),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if not requirements:
        return {}

    progress = await load_progress(db, user_id, list(requirements), now)
    challenges, skills, categories = await _label_lookups(db, list(requirements))

    by_challenge: dict[UUID, list[UnlockRequirement]] = {}
    by_category: dict[UUID, list[UnlockRequirement]] = {}
    for requirement in requirements:
        if requirement.challenge_id is not None:
            by_challenge.setdefault(requirement.challenge_id, []).append(requirement)
        elif requirement.category_id is not None:
            by_category.setdefault(requirement.category_id, []).append(requirement)

    result: dict[UUID, GateStatus] = {}
    for challenge_id in challenge_ids:
        group = list(by_challenge.get(challenge_id, []))
        category_id = challenge_to_category.get(challenge_id)
        if category_id is not None:
            group += by_category.get(category_id, [])
        if not group:
            continue
        views = [_evaluate(r, progress, challenges, skills, categories) for r in group]
        result[challenge_id] = GateStatus(
            locked=not all(v.met for v in views),
            visible_requirements=[v for v in views if _is_visible(v, challenges, now)],
        )
    return result
