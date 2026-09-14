"""Loot boxes: awarding them, opening them, and wearing what comes out (spec 038).

Most achievements drop a box; the rest carry a line saying why not. A box has a
type and a rarity, and that pair selects from an authored pool of titles. A
title is cosmetic — it sits next to a name on the scoreboard and does nothing
else, which is the line 015 and 016 both drew.

Two rules do most of the work here:

**Platinum and above are one of a kind.** Once such a title is awarded to
anybody it is never offered again, because two identical legendary titles side
by side on the board would undo the point of them.

**Uniqueness creates exhaustion, and generation absorbs it.** A popular platinum
achievement earned by fifty players needs fifty distinct titles. The model
supplies what the authored pool runs out of; when the model is unavailable *and*
the pool is empty, the box refuses to open rather than handing out a duplicate.
"""

import asyncio
import re
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, NotFoundError
from app.logging import get_logger
from app.models.challenge import Category, Challenge
from app.models.notification import (
    UNIQUE_RARITIES,
    Achievement,
    LootBox,
    LootBoxType,
    LootItem,
    LootRarity,
    NotificationKind,
)
from app.models.user import User
from app.services import ai_client, notifications
from app.services.guardrails import runner as guardrail_runner

logger = get_logger(__name__)

#: Silver splits two ways: what a Crawler did well, and what they did loudly.
_PROGRESS_FAMILY = frozenset(
    {
        LootBoxType.ADVENTURER,
        LootBoxType.CARTOGRAPHER,
        LootBoxType.SPECIALIST,
        LootBoxType.PATHFINDER,
        LootBoxType.PURIST,
    }
)

#: Boss tiers map straight onto loot rarity — 031 already decided this.
BOSS_TIER_RARITY = {
    "neighborhood": LootRarity.BRONZE,
    "borough": LootRarity.SILVER,
    "city": LootRarity.GOLD,
    "province": LootRarity.PLATINUM,
    "country": LootRarity.LEGENDARY,
    "floor": LootRarity.CELESTIAL,
}

#: How long the model gets before the authored pool takes over.
GENERATION_TIMEOUT_SECONDS = 6.0

#: A generated title is a few words. Given latitude a model writes a paragraph.
MAX_TITLE_LENGTH = 60

#: core.md forbids the System inventing loot, meaning flags. This is the one
#: place the platform deliberately generates something *called* loot, so the
#: rule needs restating: nothing flag-shaped may ever come out of it.
_FLAG_SHAPED = re.compile(r"[A-Za-z0-9_]{2,}\s*\{.*\}|flag\s*\{", re.IGNORECASE)


class BoxNotReady(AppError):
    status_code = 503
    code = "loot_unavailable"
    message = "Nothing to give you yet. Come back shortly."


def pool_key(box_type: LootBoxType, rarity: LootRarity) -> str:
    """Which catalogue a box draws from.

    Low tiers share — a bronze Adventurer's Box and a bronze Brute Force Box are
    both boring, and there is no reason to keep two sets of boring titles. Gold
    and above are per box type, where the box's identity should come through.
    """
    if box_type is LootBoxType.BOSS:
        return LootBoxType.BOSS.value
    if rarity is LootRarity.BRONZE:
        return "common"
    if rarity is LootRarity.SILVER:
        return "progress" if box_type in _PROGRESS_FAMILY else "mischief"
    return box_type.value


async def rarity_for(db: AsyncSession, achievement: Achievement) -> LootRarity | None:
    """The tier this achievement's box lands at.

    Boss achievements store none: the tier set on the challenge in 031 supplies
    it, so that fact is configured once rather than twice.
    """
    if achievement.loot_rarity is not None:
        return achievement.loot_rarity
    if achievement.loot_box_type is not LootBoxType.BOSS:
        return None

    slug = achievement.code.removeprefix("boss_")
    tier = await db.scalar(
        select(Challenge.boss_tier)
        .join(Category, Category.id == Challenge.category_id)
        .where(Category.slug == slug, Challenge.boss_tier.is_not(None))
    )
    return BOSS_TIER_RARITY.get(tier.value) if tier is not None else None


async def award_box(db: AsyncSession, user_id: UUID, achievement: Achievement) -> LootBox | None:
    """Drop a box for a newly earned achievement, if it drops one at all.

    Returns None for the 36 that pay out nothing — their `no_loot_line` is what
    the player gets instead.
    """
    if achievement.loot_box_type is None:
        return None
    rarity = await rarity_for(db, achievement)
    if rarity is None:
        # A boss achievement whose zone has no boss flagged. Nothing to size the
        # box by, so nothing is dropped.
        return None

    box = LootBox(
        user_id=user_id,
        achievement_id=achievement.id,
        box_type=achievement.loot_box_type,
        rarity=rarity,
    )
    try:
        # A savepoint: losing the race must not discard the award that caused it.
        async with db.begin_nested():
            db.add(box)
    except IntegrityError:
        return None
    return box


@dataclass(frozen=True)
class Opened:
    box_id: UUID
    title: str
    rarity: str
    box_type: str
    generated: bool


async def open_box(
    db: AsyncSession,
    user_id: UUID,
    box_id: UUID,
    *,
    settings: Settings,
    redis: Redis | None = None,
) -> Opened:
    """Resolve a box into a title.

    Idempotent: the item is written to the box row, so a double-click cannot
    reroll it. Players will absolutely try.
    """
    box = await db.scalar(select(LootBox).where(LootBox.id == box_id, LootBox.user_id == user_id))
    if box is None:
        raise NotFoundError("No such box.")

    if box.item_id is not None:
        existing = await db.get(LootItem, box.item_id)
        return Opened(
            box_id=box.id,
            title=existing.title if existing else "",
            rarity=box.rarity.value,
            box_type=box.box_type.value,
            generated=bool(existing and existing.generated),
        )

    item = await _pick(db, user_id, box, settings=settings)
    if item is None:
        raise BoxNotReady("The stores are empty and I am not repeating myself. Try again shortly.")

    box.item_id = item.id
    box.opened_at = func.now()
    await db.flush()

    await notifications.notify(
        db,
        user_id=user_id,
        kind=NotificationKind.ACHIEVEMENT,
        title=item.title,
        body=f"Opened: a {box.rarity.value} {box.box_type.value.replace('_', ' ')} box.",
        link="/character",
        redis=redis,
    )
    return Opened(
        box_id=box.id,
        title=item.title,
        rarity=box.rarity.value,
        box_type=box.box_type.value,
        generated=item.generated,
    )


async def _pick(
    db: AsyncSession, user_id: UUID, box: LootBox, *, settings: Settings
) -> LootItem | None:
    """Choose a title for this box, generating one if the tier warrants it."""
    key = pool_key(box.box_type, box.rarity)
    unique = box.rarity in UNIQUE_RARITIES

    if unique:
        # The high tiers are where a bespoke line is actually a reward, and
        # where the authored pool will eventually run dry.
        generated = await _generate(db, box, key, settings=settings)
        if generated is not None:
            return generated

    taken = select(LootBox.item_id).where(LootBox.item_id.is_not(None))
    if not unique:
        # Only this player's own holdings matter at the common tiers.
        taken = taken.where(LootBox.user_id == user_id)

    stmt = (
        select(LootItem)
        .where(
            LootItem.pool_key == key,
            LootItem.rarity == box.rarity,
            LootItem.id.not_in(taken),
        )
        .order_by(func.random())
        .limit(1)
    )
    item = await db.scalar(stmt)
    if item is not None:
        return item

    if unique:
        # Generation failed and every authored title is spoken for. Refusing is
        # better than handing out a duplicate to save face.
        return None

    # At the common tiers the player simply has everything; hand back a repeat
    # rather than refusing, since the pools are shared and shallow by design.
    return await db.scalar(
        select(LootItem)
        .where(LootItem.pool_key == key, LootItem.rarity == box.rarity)
        .order_by(func.random())
        .limit(1)
    )


async def _generate(
    db: AsyncSession, box: LootBox, key: str, *, settings: Settings
) -> LootItem | None:
    """Ask the model for a title nobody has. Any failure returns None."""
    if not settings.ai_enabled or not settings.ai_configured:
        return None

    prompt = (
        "You name trophies for a sanctioned dungeon crawl. Reply with one title "
        "and nothing else: two to five words, title case, no quotes, no "
        "punctuation at the end, no explanation.\n"
        f"It marks a {box.rarity.value}-tier {box.box_type.value.replace('_', ' ')} "
        "achievement. Dry, understated, faintly contemptuous. Never mention a "
        "flag, a code, or anything in braces."
    )
    try:
        reply = await asyncio.wait_for(
            ai_client.complete(
                settings,
                [ai_client.ChatMessage(role="user", content=prompt)],
                temperature=1.0,
                max_tokens=24,
            ),
            timeout=GENERATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.info("loot_generation_timeout", extra={"rarity": box.rarity.value})
        return None

    if not reply.ok or not reply.content:
        return None

    title = _clean(reply.content)
    if title is None:
        return None

    screened = await guardrail_runner.screen_reply(title, db, settings)
    if screened.deflect:
        logger.info("loot_generation_deflected", extra={"rarity": box.rarity.value})
        return None

    item = LootItem(pool_key=key, rarity=box.rarity, title=title, generated=True)
    try:
        # Kept in the catalogue so it can be audited afterwards, and promoted
        # into the authored list if it turned out well.
        async with db.begin_nested():
            db.add(item)
    except IntegrityError:
        # The model produced something already in the pool. Harmless, but it is
        # not a new unique title, so fall through to the authored path.
        return None
    return item


def _clean(raw: str) -> str | None:
    """Take a title out of a model reply, or refuse it."""
    title = raw.strip().strip('"').strip("'").splitlines()[0].strip()
    title = title.rstrip(".!,;:")
    if not title or len(title) > MAX_TITLE_LENGTH:
        return None
    if _FLAG_SHAPED.search(title):
        # A title containing something flag-shaped would be poison: a player
        # would submit it.
        logger.warning("loot_generation_flag_shaped")
        return None
    if len(title.split()) > 6:
        return None
    return title


async def inventory(db: AsyncSession, user_id: UUID) -> list[LootBox]:
    """Unopened boxes, oldest first — the queue as the player sees it."""
    return list(
        (
            await db.execute(
                select(LootBox)
                .where(LootBox.user_id == user_id, LootBox.item_id.is_(None))
                .order_by(LootBox.created_at)
            )
        )
        .scalars()
        .all()
    )


async def collection(db: AsyncSession, user_id: UUID) -> list[tuple[LootBox, LootItem]]:
    """Titles this player holds, rarest first."""
    rows = (
        await db.execute(
            select(LootBox, LootItem)
            .join(LootItem, LootItem.id == LootBox.item_id)
            .where(LootBox.user_id == user_id)
        )
    ).all()
    order = {r: i for i, r in enumerate(reversed(list(LootRarity)))}
    return sorted(rows, key=lambda row: order.get(row[0].rarity, 99))


async def equip(db: AsyncSession, user_id: UUID, item_id: UUID | None) -> None:
    """Wear one title, or none. Only something the player actually holds."""
    if item_id is not None:
        held = await db.scalar(
            select(LootBox.id).where(LootBox.user_id == user_id, LootBox.item_id == item_id)
        )
        if held is None:
            raise NotFoundError("You do not hold that title.")
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")
    user.equipped_title_id = item_id
    await db.flush()


async def equipped_titles(db: AsyncSession) -> dict[UUID, str]:
    """Every worn title, for the scoreboard. One query for the whole board."""
    rows = (
        await db.execute(
            select(User.id, LootItem.title).join(LootItem, LootItem.id == User.equipped_title_id)
        )
    ).all()
    return dict(rows)
