"""Bulk operations over selected challenges (spec 042).

Setting an event up means passes over whole zones — publishing a wing, retuning
its XP, deleting a draft area that did not work out. Doing that one challenge at
a time through a form is not a workflow at 242.

Two decisions shape this module:

**Per-item results, not all-or-nothing.** The CSV importer refuses a whole file
if any row is bad, and that is right for it: a half-imported file cannot be read
back. This is the opposite. A challenge with solves cannot be deleted, so a
selection of eleven may contain two that are impossible — and refusing the other
nine because of them would be obstructive. Each item succeeds or fails on its
own and the caller is told which.

**One audit entry per operation, not per challenge.** A bulk edit is one
decision. 242 audit rows for it would bury everything else in the log.
"""

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.challenge import (
    MINIMUM_POINTS_FRACTION,
    Challenge,
    ChallengeState,
    Difficulty,
)
from app.models.play import Solve
from app.models.skill import ChallengeSkill, Skill

#: A request-size and transaction-length bound, not a safety rail. The whole
#: event is 242, so this is never reached in practice.
MAX_IDS = 500


class BulkAction(enum.StrEnum):
    SET_STATE = "set_state"
    SET_DIFFICULTY = "set_difficulty"
    SET_XP = "set_xp"
    ADD_SKILLS = "add_skills"
    REMOVE_SKILLS = "remove_skills"
    SET_RELEASE_AT = "set_release_at"
    DELETE = "delete"


class BulkRejected(AppError):
    status_code = 422
    code = "bulk_rejected"
    message = "That bulk operation could not be run."


@dataclass
class ItemResult:
    challenge_id: UUID
    ok: bool
    #: Why not, in words an admin can act on — "3 players have solved this."
    reason: str | None = None


@dataclass
class BulkResult:
    succeeded: int = 0
    failed: int = 0
    results: list[ItemResult] = field(default_factory=list)
    #: Zones that no longer exist because their last challenge left. Reported
    #: because it is invisible from the selection — see :func:`_delete`.
    categories_deleted: list[str] = field(default_factory=list)


async def apply(
    db: AsyncSession, action: BulkAction, challenge_ids: list[UUID], value: object
) -> BulkResult:
    if not challenge_ids:
        raise BulkRejected("No challenges were selected.")
    if len(challenge_ids) > MAX_IDS:
        raise BulkRejected(f"At most {MAX_IDS} challenges at a time; {len(challenge_ids)} given.")

    # Deduplicated, because a selection built from a zone header plus individual
    # clicks can legitimately contain the same id twice.
    unique = list(dict.fromkeys(challenge_ids))
    challenges = {
        c.id: c
        for c in (await db.execute(select(Challenge).where(Challenge.id.in_(unique))))
        .scalars()
        .all()
    }

    result = BulkResult()
    missing = [cid for cid in unique if cid not in challenges]
    for challenge_id in missing:
        # Already gone — someone else deleted it, or the selection is stale.
        result.failed += 1
        result.results.append(ItemResult(challenge_id, False, "No longer exists."))

    present = [challenges[cid] for cid in unique if cid in challenges]
    if not present:
        return result

    if action is BulkAction.DELETE:
        await _delete(db, present, result)
    elif action is BulkAction.ADD_SKILLS:
        await _change_skills(db, present, value, result, add=True)
    elif action is BulkAction.REMOVE_SKILLS:
        await _change_skills(db, present, value, result, add=False)
    else:
        _set_field(action, present, value, result)

    await db.flush()
    return result


def _set_field(
    action: BulkAction, challenges: list[Challenge], value: object, result: BulkResult
) -> None:
    """The scalar edits. None of them can fail per-item — the value is validated
    once, up front, and then applies to every row."""
    for challenge in challenges:
        if action is BulkAction.SET_STATE:
            challenge.state = ChallengeState(str(value))
        elif action is BulkAction.SET_DIFFICULTY:
            # Deliberately does not touch XP. Spec 040 made difficulty a label;
            # a bulk relabel that silently re-priced a zone would undo that.
            challenge.difficulty = Difficulty(str(value))
        elif action is BulkAction.SET_XP:
            challenge.initial_points = _new_xp(challenge.initial_points, value)
            challenge.minimum_points = min(
                challenge.minimum_points,
                max(1, int(challenge.initial_points * MINIMUM_POINTS_FRACTION)),
            )
        elif action is BulkAction.SET_RELEASE_AT:
            challenge.release_at = datetime.fromisoformat(str(value)) if value is not None else None
        result.succeeded += 1
        result.results.append(ItemResult(challenge.id, True))


def _new_xp(current: int, value: object) -> int:
    """Absolute, or relative to each challenge's own value.

    Relative is the case this exists for: "everything in Crypto is worth 25 more"
    is one action, where an absolute value would flatten a zone's whole spread to
    a single number.
    """
    raw = str(value).strip()
    if raw.endswith("%") and raw[0] in "+-":
        percent = float(raw[:-1])
        return max(1, round(current * (1 + percent / 100)))
    if raw[0] in "+-":
        return max(1, current + int(raw))
    absolute = int(raw)
    if absolute < 1:
        raise BulkRejected("XP must be at least 1.")
    return absolute


def validate_value(action: BulkAction, value: object) -> None:
    """Refuse a bad value once, before anything is written.

    Per-item failure is right for what is genuinely per-item — a challenge with
    solves. A malformed difficulty is not: it would fail identically on all 242,
    and reporting it 242 times is noise.
    """
    if action is BulkAction.SET_STATE:
        _require_enum(ChallengeState, value, "state")
    elif action is BulkAction.SET_DIFFICULTY:
        _require_enum(Difficulty, value, "difficulty")
    elif action is BulkAction.SET_XP:
        try:
            _new_xp(100, value)
        except (ValueError, IndexError) as exc:
            raise BulkRejected(
                f"{value!r} is not an XP value. Use a number, or +25 / -10%."
            ) from exc
    elif action is BulkAction.SET_RELEASE_AT:
        if value is not None:
            try:
                datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise BulkRejected(f"{value!r} is not an ISO timestamp.") from exc
    elif action in (BulkAction.ADD_SKILLS, BulkAction.REMOVE_SKILLS) and (
        not isinstance(value, list) or not value
    ):
        raise BulkRejected("Name at least one skill.")


def _require_enum(enum_type: type[enum.StrEnum], value: object, label: str) -> None:
    try:
        enum_type(str(value))
    except ValueError as exc:
        raise BulkRejected(
            f"{value!r} is not a {label}. One of: " + ", ".join(m.value for m in enum_type)
        ) from exc


async def _change_skills(
    db: AsyncSession,
    challenges: list[Challenge],
    value: object,
    result: BulkResult,
    *,
    add: bool,
) -> None:
    """Additive and subtractive, never "replace".

    Applying a shared skill across a zone is the real use. Replace would be the
    same gesture with a silent wipe of every per-challenge mapping attached to it.
    """
    names = [str(name).strip() for name in (value if isinstance(value, list) else [])]
    found = {
        name.lower(): skill_id
        for skill_id, name in (
            await db.execute(select(Skill.id, Skill.name).where(Skill.name.in_(names)))
        ).all()
    }
    unknown = [name for name in names if name.lower() not in found]
    if unknown:
        # Refused for the whole operation: a typo would otherwise quietly apply
        # to nothing, 242 times over.
        raise BulkRejected(f"No skill named {unknown[0]!r}.")

    skill_ids = list(found.values())
    challenge_ids = [c.id for c in challenges]

    if add:
        existing = {
            (challenge_id, skill_id)
            for challenge_id, skill_id in (
                await db.execute(
                    select(ChallengeSkill.challenge_id, ChallengeSkill.skill_id).where(
                        ChallengeSkill.challenge_id.in_(challenge_ids),
                        ChallengeSkill.skill_id.in_(skill_ids),
                    )
                )
            ).all()
        }
        for challenge_id in challenge_ids:
            for skill_id in skill_ids:
                if (challenge_id, skill_id) not in existing:
                    db.add(ChallengeSkill(challenge_id=challenge_id, skill_id=skill_id))
    else:
        await db.execute(
            ChallengeSkill.__table__.delete().where(
                ChallengeSkill.challenge_id.in_(challenge_ids),
                ChallengeSkill.skill_id.in_(skill_ids),
            )
        )

    for challenge_id in challenge_ids:
        result.succeeded += 1
        result.results.append(ItemResult(challenge_id, True))


async def _delete(db: AsyncSession, challenges: list[Challenge], result: BulkResult) -> None:
    """Delete what can be deleted; report what cannot.

    A challenge with solves is refused — deleting it would erase what scored for
    people, and hiding is the operation actually wanted. That refusal is
    per-challenge, so a selection of eleven containing two solved ones removes
    nine rather than none. Clearing the solves deliberately, with the event
    reset (spec 043), is how a scaffolding challenge becomes deletable.
    """
    solved = dict(
        (
            await db.execute(
                select(Solve.challenge_id, func.count(func.distinct(Solve.user_id)))
                .where(Solve.challenge_id.in_([c.id for c in challenges]))
                .group_by(Solve.challenge_id)
            )
        ).all()
    )

    for challenge in challenges:
        count = solved.get(challenge.id, 0)
        if count:
            result.failed += 1
            result.results.append(
                ItemResult(
                    challenge.id,
                    False,
                    f"{count} player{'s' if count != 1 else ''} have solved this. Hide it instead.",
                )
            )
            continue
        await db.delete(challenge)
        result.succeeded += 1
        result.results.append(ItemResult(challenge.id, True))

    await db.flush()
    # `categories_deleted` stays empty: zones are no longer pruned when their
    # last challenge goes (spec 043). The field is kept so a client written
    # against 042 keeps working.


async def preview_delete(db: AsyncSession, challenge_ids: list[UUID]) -> "DeletePreview":
    """What the confirm dialog says before anything happens.

    One thing is not visible from the selection: which rows cannot be deleted
    because people have solved them. Zones used to be the other, until spec 043
    stopped deleting them along with their last challenge.
    """
    unique = list(dict.fromkeys(challenge_ids))
    challenges = list(
        (await db.execute(select(Challenge).where(Challenge.id.in_(unique)))).scalars().all()
    )
    solved = dict(
        (
            await db.execute(
                select(Solve.challenge_id, func.count(func.distinct(Solve.user_id)))
                .where(Solve.challenge_id.in_(unique))
                .group_by(Solve.challenge_id)
            )
        ).all()
    )

    blocked = [c for c in challenges if solved.get(c.id)]
    return DeletePreview(
        deletable=len(challenges) - len(blocked),
        blocked=[
            ItemResult(c.id, False, f"{solved[c.id]} solved — hide it, or reset play data.")
            for c in blocked
        ],
        zones_emptied=[],
    )


@dataclass
class EmptiedZone:
    """Vestigial (spec 043): zones are no longer deleted with their last
    challenge, so nothing populates this any more. Kept so a client written
    against 042's response shape keeps parsing."""

    category_id: UUID
    name: str
    skills_orphaned: int


@dataclass
class DeletePreview:
    deletable: int
    blocked: list[ItemResult]
    zones_emptied: list[EmptiedZone]
