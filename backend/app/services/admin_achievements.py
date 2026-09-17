"""Admin CRUD over the achievement roster (spec 030).

Mirrors the skills and classes services in shape, with one difference that
drives the whole design: **an achievement is half data and half code.** Name,
description and earned-by are editable text; ``code`` names a trigger living in
``app.services.achievements`` that no amount of admin UI can conjure.

So this service surfaces that seam rather than hiding it. Every row reports
whether its code has a registered trigger, and the unused registered codes are
offered as suggestions — because the useful new achievement is nearly always one
whose trigger already exists.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.notification import Achievement, AchievementAward
from app.services.achievements import REGISTRY, resolve, trigger_families
from app.theme import is_secret

#: What 029's seed writes into `description`. Rows still holding it are the
#: working list for whoever is writing the System AI's copy.
PLACEHOLDER = "TODO: System AI flavour text."


class AchievementHeld(ConflictError):
    code = "achievement_held"
    message = "Players already hold this achievement."


@dataclass(frozen=True)
class AchievementRow:
    id: UUID
    code: str
    name: str
    description: str
    earned_by: str
    display_order: int
    secret: bool
    #: False when no trigger is registered for this code — the achievement is
    #: inert and will never fire. A legitimate work-in-progress state, but one
    #: that has to be visible rather than discovered after the event.
    has_trigger: bool
    #: True while `description` is still the seeded placeholder.
    needs_copy: bool
    held_by: int
    #: The reward. Editable since spec 058; before that an achievement's payout
    #: was whatever the seed said, permanently.
    loot_box_type: str | None = None
    loot_rarity: str | None = None
    no_loot_line: str | None = None
    unlocks_theme: str | None = None


async def list_achievements(db: AsyncSession) -> list[AchievementRow]:
    achievements = list(
        (
            await db.execute(
                select(Achievement).order_by(Achievement.display_order, Achievement.name)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                select(
                    AchievementAward.achievement_id, func.count(AchievementAward.user_id)
                ).group_by(AchievementAward.achievement_id)
            )
        ).all()
    )
    return [_row(a, counts.get(a.id, 0)) for a in achievements]


def _row(achievement: Achievement, held_by: int) -> AchievementRow:
    return AchievementRow(
        id=achievement.id,
        code=achievement.code,
        name=achievement.name,
        description=achievement.description,
        earned_by=achievement.earned_by,
        display_order=achievement.display_order,
        secret=achievement.secret,
        has_trigger=resolve(achievement.code) is not None,
        needs_copy=achievement.description.strip() == PLACEHOLDER,
        held_by=held_by,
        loot_box_type=achievement.loot_box_type.value if achievement.loot_box_type else None,
        loot_rarity=achievement.loot_rarity.value if achievement.loot_rarity else None,
        no_loot_line=achievement.no_loot_line,
        unlocks_theme=achievement.unlocks_theme,
    )


async def trigger_codes(db: AsyncSession) -> dict[str, list[str]]:
    """Registered trigger codes, split by whether a row already uses them.

    The unused half is the suggestion list when creating: a trigger with no
    achievement is the mirror image of an achievement with no trigger, and just
    as worth surfacing.
    """
    used = set((await db.execute(select(Achievement.code))).scalars().all())
    registered = sorted(REGISTRY)
    return {
        "registered": registered,
        "unused": [code for code in registered if code not in used],
        # Families resolve a code that is not known until the data is, so they
        # cannot be listed as concrete suggestions — only described.
        "families": trigger_families(),
    }


async def create(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    description: str = PLACEHOLDER,
    earned_by: str = "",
    display_order: int = 0,
    secret: bool = False,
    loot_box_type: object = None,
    loot_rarity: object = None,
    no_loot_line: str | None = None,
    unlocks_theme: str | None = None,
) -> AchievementRow:
    await _check_free(db, code=code, name=name)
    _check_theme(unlocks_theme)
    achievement = Achievement(
        code=code.strip(),
        name=name.strip(),
        description=description,
        earned_by=earned_by,
        display_order=display_order,
        secret=secret,
        loot_box_type=loot_box_type,
        loot_rarity=loot_rarity,
        no_loot_line=no_loot_line,
        unlocks_theme=unlocks_theme,
    )
    db.add(achievement)
    await db.flush()
    return _row(achievement, 0)


async def update(db: AsyncSession, achievement_id: UUID, *, changes: dict) -> AchievementRow:
    """Everything but the code.

    A code joins to a trigger *and* to every award already granted, so renaming
    one would silently orphan both. Fixing a typo in a code is a delete and a
    create, which is the honest cost.
    """
    achievement = await get(db, achievement_id)
    changes.pop("code", None)

    new_name = changes.get("name")
    if new_name is not None and new_name != achievement.name:
        await _check_free(db, name=new_name, exclude=achievement_id)

    # PATCH cannot tell "not sent" from "set to null", and null *is* the cleared
    # value for a reward — so clearing one is an explicit flag rather than an
    # omission that could never be expressed.
    if changes.pop("clear_loot", False):
        achievement.loot_box_type = None
        achievement.loot_rarity = None
    if changes.pop("clear_theme", False):
        achievement.unlocks_theme = None

    if "unlocks_theme" in changes:
        _check_theme(changes["unlocks_theme"])

    for field, value in changes.items():
        setattr(achievement, field, value)
    await db.flush()
    return _row(achievement, await held_count(db, achievement_id))


def _check_theme(theme: str | None) -> None:
    """A theme that is not secret is not a reward.

    The everyday themes are already everybody's, so attaching one would be an
    achievement that grants what the player already had.
    """
    if theme is None:
        return
    if not is_secret(theme):
        raise ConflictError(f"{theme} is not a grantable theme.", code="theme_not_grantable")


async def delete(db: AsyncSession, achievement_id: UUID) -> None:
    """Refused once anyone holds it.

    Taking an achievement back from a player who earned it is worse than living
    with a badly-named one, and the FK cascade would do exactly that silently.
    Hiding it with the secret flag is the reversible alternative.
    """
    achievement = await get(db, achievement_id)
    held = await held_count(db, achievement_id)
    if held:
        raise AchievementHeld(
            f"{held} {'player holds' if held == 1 else 'players hold'} this achievement. "
            "Mark it secret to hide it instead."
        )
    await db.delete(achievement)
    await db.flush()


async def get(db: AsyncSession, achievement_id: UUID) -> Achievement:
    achievement = await db.get(Achievement, achievement_id)
    if achievement is None:
        raise NotFoundError("No such achievement.")
    return achievement


async def held_count(db: AsyncSession, achievement_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(AchievementAward.id)).where(
                AchievementAward.achievement_id == achievement_id
            )
        )
    ) or 0


async def _check_free(
    db: AsyncSession,
    *,
    code: str | None = None,
    name: str | None = None,
    exclude: UUID | None = None,
) -> None:
    """Both are unique in the database; the error says which one clashed."""
    for field, value, message, error_code in (
        (Achievement.code, code, "An achievement with that code already exists.", "code_taken"),
        (Achievement.name, name, "An achievement with that name already exists.", "name_taken"),
    ):
        if value is None:
            continue
        stmt = select(Achievement.id).where(field == value.strip())
        if exclude is not None:
            stmt = stmt.where(Achievement.id != exclude)
        if await db.scalar(stmt):
            raise ConflictError(message, code=error_code)
