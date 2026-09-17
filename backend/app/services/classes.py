"""Character classes — admin CRUD and the affinity-skill link (spec 016).

Mirrors the skill service in shape. A class carries an optional affinity skill;
deleting that skill un-links it (the FK is ``ON DELETE SET NULL``), and deleting a
class returns its players to Classless the same way. A class never touches
scoring — this is roster management only.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.challenge import Ability
from app.models.character_class import CharacterClass, ClassPreference, ClassRequirement, Rarity
from app.models.skill import Skill
from app.services import scoring


async def list_classes(db: AsyncSession) -> list[CharacterClass]:
    return list(
        (
            await db.execute(
                select(CharacterClass).order_by(CharacterClass.display_order, CharacterClass.name)
            )
        )
        .scalars()
        .all()
    )


async def get_class(db: AsyncSession, class_id: UUID) -> CharacterClass:
    character_class = await db.get(CharacterClass, class_id)
    if character_class is None:
        raise NotFoundError("No such class.")
    return character_class


async def create_class(
    db: AsyncSession,
    *,
    name: str,
    display_order: int = 0,
    description: str | None = None,
    rarity: Rarity | None = None,
) -> CharacterClass:
    if await db.scalar(select(CharacterClass.id).where(CharacterClass.name == name)):
        raise ConflictError("A class with that name already exists.", code="class_exists")

    character_class = CharacterClass(
        name=name,
        display_order=display_order,
        description=description,
        # Presentation only, and the model defaults it — but a create form that
        # cannot set it would mean every new class arriving as common.
        rarity=rarity or Rarity.COMMON,
    )
    db.add(character_class)
    await db.flush()
    return character_class


async def update_class(db: AsyncSession, class_id: UUID, *, changes: dict) -> CharacterClass:
    character_class = await get_class(db, class_id)

    new_name = changes.get("name")
    if new_name is not None and new_name != character_class.name:
        clash = await db.scalar(
            select(CharacterClass.id).where(
                CharacterClass.name == new_name, CharacterClass.id != class_id
            )
        )
        if clash:
            raise ConflictError("A class with that name already exists.", code="class_exists")

    for field, value in changes.items():
        setattr(character_class, field, value)
    await db.flush()
    return character_class


async def delete_class(db: AsyncSession, class_id: UUID) -> None:
    character_class = await get_class(db, class_id)
    # ON DELETE SET NULL returns this class's players to Classless.
    await db.delete(character_class)
    await db.flush()


@dataclass(frozen=True)
class ClassStanding:
    """A class as one player sees it (spec 024)."""

    character_class: CharacterClass
    unlocked: bool
    #: 0..1, how well this player's strengths match the class's targets. Only
    #: meaningful for an unlocked class, which is the only kind ever shown.
    affinity: float


async def standings(db: AsyncSession, user_id: UUID) -> list[ClassStanding]:
    """Every class, scored and marked unlocked, for one player.

    Locked classes are returned here because callers need to *filter* them; the
    player-facing API drops them entirely. 024 makes the roster a mystery — a
    class a player has not earned must not appear at all, not even greyed.
    """
    classes = await list_classes(db)
    skill_xp = await scoring.skill_xp_for_user(db, user_id)
    ability_xp = await scoring.ability_xp_for_user(db, user_id)

    levels = {skill_id: scoring.skill_level(xp) for skill_id, xp in skill_xp.items()}

    # Each target is scored against the player's own best in *that* dimension.
    # Raw values cannot be compared: an ability pools whole categories, so
    # ability XP dwarfs any single skill's and a naive sum would hand every
    # recommendation to the ability-target classes.
    best_skill = max(skill_xp.values(), default=0)
    best_ability = max(ability_xp.values(), default=0)

    out: list[ClassStanding] = []
    for character_class in classes:
        unlocked = all(
            levels.get(req.skill_id, 0) >= req.min_level for req in character_class.requirements
        )

        shares: list[float] = []
        for pref in character_class.preferences:
            if pref.skill_id is not None:
                shares.append(skill_xp.get(pref.skill_id, 0) / best_skill if best_skill else 0.0)
            elif pref.ability is not None:
                shares.append(
                    ability_xp.get(pref.ability, 0) / best_ability if best_ability else 0.0
                )
        affinity = sum(shares) / len(shares) if shares else 0.0

        out.append(
            ClassStanding(character_class=character_class, unlocked=unlocked, affinity=affinity)
        )
    return out


#: Rarer first when affinity ties — it is the more interesting suggestion.
_RARITY_RANK = {
    Rarity.MYTHIC: 0,
    Rarity.LEGENDARY: 1,
    Rarity.RARE: 2,
    Rarity.UNCOMMON: 3,
    Rarity.COMMON: 4,
}


async def available_classes(db: AsyncSession, user_id: UUID) -> list[CharacterClass]:
    """The roster as this player may see it — unlocked only."""
    return [s.character_class for s in await standings(db, user_id) if s.unlocked]


#: Ability codes read as words in the nudge; "INT" is jargon in a sentence.
_ABILITY_WORDS = {
    Ability.STR: "brute-force",
    Ability.DEX: "fast-hands",
    Ability.CON: "grind-it-out",
    Ability.INT: "analytical",
    Ability.WIS: "watchful",
    Ability.CHA: "people-facing",
}


@dataclass(frozen=True)
class Suggestion:
    character_class: CharacterClass
    #: What the player has been doing, in words — a skill name, or an ability
    #: rendered as a phrase. Feeds the System AI's line.
    reason: str


async def suggest_class(db: AsyncSession, user_id: UUID) -> Suggestion | None:
    """The class that best fits what this player has actually been doing.

    Only ever names an unlocked class: suggesting one a player cannot pick would
    both frustrate them and leak the hidden roster.
    """
    ranked = [s for s in await standings(db, user_id) if s.unlocked and s.affinity > 0]
    if not ranked:
        return None
    best = min(
        ranked,
        key=lambda s: (
            -s.affinity,
            _RARITY_RANK[s.character_class.rarity],
            s.character_class.display_order,
            s.character_class.name,
        ),
    )

    # Name the target the player is actually strongest in, not just the first
    # one listed — the nudge should describe them, not the class.
    skill_xp = await scoring.skill_xp_for_user(db, user_id)
    ability_xp = await scoring.ability_xp_for_user(db, user_id)
    reason = best.character_class.name
    top = -1.0
    for pref in best.character_class.preferences:
        if pref.skill_id is not None:
            value = skill_xp.get(pref.skill_id, 0)
            label = await db.scalar(select(Skill.name).where(Skill.id == pref.skill_id))
        else:
            value = ability_xp.get(pref.ability, 0)
            label = _ABILITY_WORDS.get(pref.ability)
        if label and value > top:
            top, reason = value, label
    return Suggestion(character_class=best.character_class, reason=reason)


async def set_preferences(
    db: AsyncSession, class_id: UUID, preferences: list[dict]
) -> CharacterClass:
    """Replace the whole set (spec 058 §3).

    Replacing rather than patching, matching `PUT /admin/challenges/{id}/skills`:
    an admin should never have to reason about which of several calls left the
    class in the state it is in.

    The XOR is checked here as well as by the database CHECK, so a bad request
    comes back as an explanation rather than an integrity error.
    """
    character_class = await get_class(db, class_id)

    for index, entry in enumerate(preferences):
        ability = entry.get("ability")
        skill_id = entry.get("skill_id")
        if bool(ability) == bool(skill_id):
            raise ConflictError(
                f"Preference {index + 1} must name exactly one of an ability or a skill.",
                code="preference_not_exclusive",
            )

    await db.execute(delete(ClassPreference).where(ClassPreference.class_id == class_id))
    for entry in preferences:
        db.add(
            ClassPreference(
                class_id=class_id,
                ability=entry.get("ability"),
                skill_id=entry.get("skill_id"),
            )
        )
    await db.flush()
    await db.refresh(character_class)
    return character_class


async def set_requirements(
    db: AsyncSession, class_id: UUID, requirements: list[dict]
) -> CharacterClass:
    """Replace the whole set. One requirement per skill, as the model enforces."""
    character_class = await get_class(db, class_id)

    seen: set[UUID] = set()
    for entry in requirements:
        skill_id = entry["skill_id"]
        if skill_id in seen:
            raise ConflictError(
                "A class cannot require the same skill twice.",
                code="duplicate_requirement",
            )
        seen.add(skill_id)

    await db.execute(delete(ClassRequirement).where(ClassRequirement.class_id == class_id))
    for entry in requirements:
        db.add(
            ClassRequirement(
                class_id=class_id,
                skill_id=entry["skill_id"],
                min_level=entry["min_level"],
            )
        )
    await db.flush()
    await db.refresh(character_class)
    return character_class
