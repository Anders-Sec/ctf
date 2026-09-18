"""The authored accessory roster (spec 073 §2).

Kept in the repo and seeded into the table at boot: versioned here, editable
there. An operator tuning an anchor during setup should not need a deploy, and
a fresh instance should not need an operator.

Seeded at startup rather than by a migration, which is a deliberate difference
from the class roster (migration 0027). Migrations in this repo never import
from ``app`` — they are frozen snapshots — so a migration would mean a second
copy of this list in SQL, and two copies is one too many.

Art lives in object storage under ``image_key``; this file is the *rules*. A
row whose art has not been uploaded still seeds — it simply renders nothing
until the PNG arrives, which is the right failure for a roster that is authored
before the art is drawn.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.avatar import AccessorySlot, AvatarAccessory, UnlockKind
from app.models.character_class import Rarity

logger = get_logger(__name__)


@dataclass(frozen=True)
class Authored:
    slug: str
    name: str
    slot: AccessorySlot
    rarity: Rarity
    unlock_kind: UnlockKind
    unlock_ref: str | None
    description: str
    #: Fractions of the canvas. The sigil is drawn to a fixed template and
    #: corporate photos are all the same angle, so one anchor is close enough
    #: for most people and the editor handles the rest.
    anchor: tuple[float, float, float, float] = (0.5, 0.30, 1.0, 0.0)


#: Everybody's, from the first minute. Day-one emptiness is the point elsewhere
#: (spec 060 §9), but an avatar you cannot change at all is not emptiness, it is
#: a wall — so there is a small starter set.
_STARTERS = [
    Authored(
        "hood-plain",
        "Plain Hood",
        AccessorySlot.HEAD,
        Rarity.COMMON,
        UnlockKind.ALWAYS,
        None,
        "Undyed wool. It keeps the rain off and asks no questions.",
    ),
    Authored(
        "band-leather",
        "Leather Band",
        AccessorySlot.HEAD,
        Rarity.COMMON,
        UnlockKind.ALWAYS,
        None,
        "Holds your hair back. That is the entire feature set.",
    ),
    Authored(
        "spectacles",
        "Spectacles",
        AccessorySlot.EYES,
        Rarity.COMMON,
        UnlockKind.ALWAYS,
        None,
        "For reading the small print on a cursed scroll.",
        anchor=(0.5, 0.42, 0.8, 0.0),
    ),
    Authored(
        "cloak-travelling",
        "Travelling Cloak",
        AccessorySlot.SHOULDERS,
        Rarity.COMMON,
        UnlockKind.ALWAYS,
        None,
        "Road-stained and warm. Everyone starts with one.",
        anchor=(0.5, 0.70, 1.2, 0.0),
    ),
]

#: Class-locked. The point of the whole feature: a class choice is currently
#: invisible to everybody else, and a hat fixes that across the scoreboard, the
#: party page and the roster at once.
#:
#: ``unlock_ref`` is the class **name** exactly as migration 0027 seeds it, and
#: the accessory's rarity matches the class's own so the two colour ladders
#: agree. The first draft of this list invented a "Paladin" that is not in the
#: 48-class roster — a dead accessory nobody could ever earn. `test_roster`
#: now checks every ref against the real roster.
_CLASS_PIECES = [
    (
        "wizard",
        "Wizard",
        "Pointed Hat",
        Rarity.COMMON,
        "Wide-brimmed, star-strewn, and slightly too large. Traditional.",
    ),
    (
        "rogue",
        "Rogue",
        "Shadowed Cowl",
        Rarity.COMMON,
        "You were not seen arriving and you will not be seen leaving.",
    ),
    (
        "cleric",
        "Cleric",
        "Holy Circlet",
        Rarity.COMMON,
        "It glows faintly. Nobody has worked out from what.",
    ),
    (
        "ranger",
        "Ranger",
        "Hunter's Hood",
        Rarity.COMMON,
        "Green, quiet, and smells faintly of pine.",
    ),
    ("bard", "Bard", "Feathered Cap", Rarity.COMMON, "The feather is load-bearing."),
    ("druid", "Druid", "Antlered Crown", Rarity.COMMON, "Grown, not made. It is still growing."),
    (
        "warlock",
        "Warlock",
        "Horned Diadem",
        Rarity.COMMON,
        "The terms of your arrangement are inscribed inside. Do not read them.",
    ),
    (
        "cipher-adept",
        "Cipher Adept",
        "Cipher Mask",
        Rarity.UNCOMMON,
        "The engraving rearranges itself when you are not looking at it.",
    ),
    (
        "shadow-broker",
        "Shadow Broker",
        "Broker's Veil",
        Rarity.UNCOMMON,
        "Everything is for sale. Your face is not included.",
    ),
    (
        "packet-sage",
        "Packet Sage",
        "Sage's Wrap",
        Rarity.UNCOMMON,
        "Woven from something that was once a cable.",
    ),
    (
        "cryptomancer",
        "Cryptomancer",
        "Sigil Crown",
        Rarity.RARE,
        "Each stone is a key. None of them are the same key twice.",
    ),
    (
        "voidcoder",
        "Voidcoder",
        "Null Halo",
        Rarity.RARE,
        "It is not there. It is definitely on your head.",
    ),
    (
        "root-ascendant",
        "Root Ascendant",
        "Ascendant's Halo",
        Rarity.LEGENDARY,
        "You own this machine now. The machine has been informed.",
    ),
    (
        "the-unwritten",
        "The Unwritten",
        "Blank Mask",
        Rarity.LEGENDARY,
        "No features. No record. No one is sure you were ever here.",
    ),
    (
        "herald-of-zero-day",
        "Herald of Zero-Day",
        "Herald's Horns",
        Rarity.LEGENDARY,
        "They curve forward, which is the direction you were already going.",
    ),
]

#: Loot-locked, on the existing rarity ladder (spec 038). A frame is the loudest
#: thing on a 40px avatar, so these are the rarest.
_LOOT_PIECES = [
    (
        "frame-bronze",
        "Bronze Frame",
        "bronze",
        Rarity.COMMON,
        "A modest border. You opened something.",
    ),
    ("frame-silver", "Silver Frame", "silver", Rarity.UNCOMMON, "It catches the torchlight."),
    ("frame-gold", "Gold Frame", "gold", Rarity.RARE, "Loud, and meant to be."),
    ("frame-platinum", "Platinum Frame", "platinum", Rarity.RARE, "Cold to the touch."),
    (
        "frame-legendary",
        "Legendary Frame",
        "legendary",
        Rarity.LEGENDARY,
        "Very few of these exist. You are holding one.",
    ),
    # The top of the loot ladder is `celestial`, not `mythic` — `mythic` is the
    # *class* ladder's top rung. Two ladders, two vocabularies, and the first
    # draft of this list confused them.
    (
        "frame-celestial",
        "Celestial Frame",
        "celestial",
        Rarity.MYTHIC,
        "The dungeon is not certain it approves.",
    ),
]

#: Achievement-locked, keyed on the achievement's **code** — its stable key.
#: ``name`` is display text an admin can rename out from under a rule.
_ACHIEVEMENT_PIECES = [
    (
        "crown-first-blood",
        "First Blood Crown",
        "first_blood",
        Rarity.RARE,
        "You were first. It is on your head now, permanently.",
        AccessorySlot.HEAD,
    ),
    (
        "mantle-conqueror",
        "Conqueror's Mantle",
        "conqueror",
        Rarity.LEGENDARY,
        "Heavy, and earned. People move aside without deciding to.",
        AccessorySlot.SHOULDERS,
    ),
    (
        "crown-whole-dungeon",
        "Dungeon-Walker's Crown",
        "whole_dungeon",
        Rarity.MYTHIC,
        "Every door. Every room. Nothing left that has not seen you.",
        AccessorySlot.HEAD,
    ),
]


def authored_roster() -> list[Authored]:
    """The full roster, assembled from the groups above."""
    roster = list(_STARTERS)

    roster += [
        Authored(
            f"hat-{slug}",
            name,
            AccessorySlot.HEAD,
            rarity,
            UnlockKind.CLASS,
            class_name,
            description,
        )
        for slug, class_name, name, rarity, description in _CLASS_PIECES
    ]
    roster += [
        Authored(
            slug,
            name,
            AccessorySlot.FRAME,
            rarity,
            UnlockKind.LOOT_RARITY,
            ref,
            description,
            anchor=(0.5, 0.5, 2.0, 0.0),
        )
        for slug, name, ref, rarity, description in _LOOT_PIECES
    ]
    roster += [
        Authored(
            slug,
            name,
            slot,
            rarity,
            UnlockKind.ACHIEVEMENT,
            code,
            description,
            anchor=(0.5, 0.28, 1.0, 0.0) if slot == AccessorySlot.HEAD else (0.5, 0.70, 1.2, 0.0),
        )
        for slug, name, code, rarity, description, slot in _ACHIEVEMENT_PIECES
    ]
    return roster


async def seed(db: AsyncSession, *, overwrite: bool = False) -> int:
    """Insert anything missing. Returns how many rows were added.

    Idempotent by slug. **Existing rows are left alone** unless `overwrite`,
    because an operator who nudged an anchor during setup should not have it
    reverted by the next deploy — the same rule the class roster follows.
    """
    existing = {slug for slug in (await db.execute(select(AvatarAccessory.slug))).scalars().all()}

    added = 0
    for item in authored_roster():
        if item.slug in existing and not overwrite:
            continue
        x, y, scale, rotation = item.anchor
        if item.slug in existing:
            row = (
                await db.execute(select(AvatarAccessory).where(AvatarAccessory.slug == item.slug))
            ).scalar_one()
        else:
            row = AvatarAccessory(slug=item.slug)
            db.add(row)
            added += 1

        row.name = item.name
        row.description = item.description
        row.slot = item.slot
        row.rarity = item.rarity
        row.unlock_kind = item.unlock_kind
        row.unlock_ref = item.unlock_ref
        row.image_key = f"accessories/{item.slug}.png"
        row.anchor_x, row.anchor_y = x, y
        row.anchor_scale, row.anchor_rotation = scale, rotation

    await db.flush()
    logger.info("accessory_roster.seeded", added=added, total=len(authored_roster()))
    return added
