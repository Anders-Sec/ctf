"""Avatars: one renderer, and unlocks that are derived rather than granted.

Spec 073. Three things live here:

- **Unlock derivation.** What accessories a player holds is computed on read
  from their class, achievements and loot — never stored. A grant table would be
  a grant table to fall out of sync, and achievements already prove this works.
- **Compositing.** Base image, then at most one accessory per slot at its stored
  transform, into the PNG that ``GET /users/{id}/avatar`` serves.
- **Validation.** A config naming an accessory the player has not unlocked is
  rejected here, server-side, against the derived set. The client's idea of what
  it owns is not evidence (specs 018, 028).

Deliberately no GPU and no network: spec 074's generation host is optional
infrastructure, and none of this may stop working when it is off.
"""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.errors import AppError
from app.logging import get_logger
from app.models.avatar import AccessorySlot, AvatarAccessory, UnlockKind
from app.models.user import AvatarSource, User
from app.services.sigils import render_sigil
from app.services.storage import StorageUnavailable, get_storage

logger = get_logger(__name__)

#: What the renderer emits and the endpoint serves. One size: the frontend
#: scales it, and storing several would be three things to keep in step.
CANVAS = 512

#: A transform may move an accessory around the canvas but not off it, and not
#: so large it becomes the whole avatar. These are the limits `PUT` enforces.
MIN_SCALE, MAX_SCALE = 0.2, 3.0


class AccessoryLocked(AppError):
    status_code = 403
    code = "accessory_locked"
    message = "You have not unlocked that yet."


class DuplicateSlot(AppError):
    status_code = 422
    code = "duplicate_accessory_slot"
    message = "Only one accessory can go in each place."


class UnknownAccessory(AppError):
    status_code = 404
    code = "unknown_accessory"
    message = "No such accessory."


class InvalidTransform(AppError):
    status_code = 422
    code = "invalid_avatar_transform"
    message = "That will not fit on the canvas."


@dataclass(frozen=True)
class Layer:
    """One accessory placed on the canvas.

    Fractions rather than pixels, so the same recipe renders at any size — which
    is the reason the *transform* is stored and not a flattened image.
    """

    accessory: str
    x: float
    y: float
    scale: float
    rotation: float


def layers_from_config(config: dict) -> list[Layer]:
    """Reads the stored recipe, tolerating anything that is not one.

    A malformed config must degrade to a bare avatar rather than 500 — this is
    read on every roster row on the scoreboard.
    """
    raw = config.get("layers") if isinstance(config, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[Layer] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("accessory"), str):
            continue
        try:
            out.append(
                Layer(
                    accessory=entry["accessory"],
                    x=float(entry.get("x", 0.5)),
                    y=float(entry.get("y", 0.5)),
                    scale=float(entry.get("scale", 1.0)),
                    rotation=float(entry.get("rotation", 0.0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def config_from_layers(layers: list[Layer]) -> dict:
    return {
        "layers": [
            {
                "accessory": layer.accessory,
                "x": layer.x,
                "y": layer.y,
                "scale": layer.scale,
                "rotation": layer.rotation,
            }
            for layer in layers
        ]
    }


async def unlocked_slugs(db: AsyncSession, user_id: UUID) -> set[str]:
    """Every accessory this player holds, derived from what they already have.

    One query per unlock kind rather than one per accessory: 200 players
    refreshing a roster is not the place for a loop of round trips.
    """
    from app.models.character_class import CharacterClass
    from app.models.notification import Achievement, AchievementAward, LootBox

    rows = (
        (await db.execute(select(AvatarAccessory).where(AvatarAccessory.enabled.is_(True))))
        .scalars()
        .all()
    )

    held: set[str] = {a.slug for a in rows if a.unlock_kind == UnlockKind.ALWAYS}

    wants_class = {a.unlock_ref for a in rows if a.unlock_kind == UnlockKind.CLASS}
    wants_achievement = {a.unlock_ref for a in rows if a.unlock_kind == UnlockKind.ACHIEVEMENT}
    wants_rarity = {a.unlock_ref for a in rows if a.unlock_kind == UnlockKind.LOOT_RARITY}

    my_class: str | None = None
    if wants_class:
        my_class = (
            await db.execute(
                select(CharacterClass.name)
                .join(User, User.character_class_id == CharacterClass.id)
                .where(User.id == user_id)
            )
        ).scalar_one_or_none()

    my_achievements: set[str] = set()
    if wants_achievement:
        # `code` is the achievement's stable key; `name` is display text that
        # the roster admin can rename out from under an unlock rule.
        my_achievements = set(
            (
                await db.execute(
                    select(Achievement.code)
                    .join(AchievementAward, AchievementAward.achievement_id == Achievement.id)
                    .where(AchievementAward.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

    my_rarities: set[str] = set()
    if wants_rarity:
        my_rarities = {
            str(value)
            for value in (
                await db.execute(
                    select(LootBox.rarity).where(LootBox.user_id == user_id).distinct()
                )
            )
            .scalars()
            .all()
        }

    # One set per kind, so adding a fifth unlock rule is a line here rather
    # than another branch in a chain.
    satisfied: dict[UnlockKind, set[str]] = {
        UnlockKind.CLASS: {my_class.lower()} if my_class else set(),
        UnlockKind.ACHIEVEMENT: my_achievements,
        UnlockKind.LOOT_RARITY: my_rarities,
    }
    for accessory in rows:
        ref = accessory.unlock_ref
        if ref is None:
            continue
        # Class names are CITEXT and admin-edited, so matched case-insensitively;
        # achievement codes and rarities are exact keys.
        needle = ref.lower() if accessory.unlock_kind == UnlockKind.CLASS else ref
        if needle in satisfied.get(accessory.unlock_kind, set()):
            held.add(accessory.slug)

    return held


async def validate_layers(
    db: AsyncSession, user_id: UUID, layers: list[Layer]
) -> list[AvatarAccessory]:
    """Server-side, against the derived set. Raises rather than silently dropping.

    Silently ignoring a locked accessory would let a player believe they had
    equipped something; refusing says what happened.
    """
    if not layers:
        return []

    slugs = [layer.accessory for layer in layers]
    rows = (
        (
            await db.execute(
                select(AvatarAccessory).where(
                    AvatarAccessory.slug.in_(slugs), AvatarAccessory.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    by_slug = {row.slug: row for row in rows}

    missing = [slug for slug in slugs if slug not in by_slug]
    if missing:
        raise UnknownAccessory()

    held = await unlocked_slugs(db, user_id)
    if any(slug not in held for slug in slugs):
        raise AccessoryLocked()

    slots = [by_slug[slug].slot for slug in slugs]
    if len(set(slots)) != len(slots):
        raise DuplicateSlot()

    for layer in layers:
        if not (MIN_SCALE <= layer.scale <= MAX_SCALE):
            raise InvalidTransform("That is too big or too small.")
        if not (-0.5 <= layer.x <= 1.5 and -0.5 <= layer.y <= 1.5):
            raise InvalidTransform()

    return [by_slug[slug] for slug in slugs]


def _place(canvas: Image.Image, art: Image.Image, layer: Layer) -> None:
    """Scale, rotate and paste one accessory at its transform."""
    target = max(8, int(CANVAS * 0.5 * layer.scale))
    art = art.convert("RGBA")
    art.thumbnail((target, target), Image.LANCZOS)
    if layer.rotation:
        # `expand` so a rotated corner is not clipped off.
        art = art.rotate(layer.rotation, resample=Image.BICUBIC, expand=True)

    left = int(CANVAS * layer.x - art.width / 2)
    top = int(CANVAS * layer.y - art.height / 2)
    canvas.alpha_composite(art, (left, top))


async def render(
    db: AsyncSession,
    user: User,
    *,
    base_override: bytes | None = None,
    settings: Settings | None = None,
) -> bytes:
    """The one rendering path: base, then the layers, into a PNG.

    Every avatar in the app comes out of here, which is what lets `Avatar` on
    the frontend be an `<img>` and nothing else.
    """
    source = user.avatar_source
    base: Image.Image

    if base_override is not None:
        base = Image.open(io.BytesIO(base_override))
    elif source in (AvatarSource.ENTRA, AvatarSource.GENERATED) and user.avatar_base:
        base = Image.open(io.BytesIO(user.avatar_base))
    else:
        # Including the case where a source says "photo" and the bytes are
        # gone: a crest is a better answer than a broken image.
        base = Image.open(io.BytesIO(render_sigil(str(user.id), CANVAS)))

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    base = base.convert("RGBA")
    if base.size != (CANVAS, CANVAS):
        base = base.resize((CANVAS, CANVAS), Image.LANCZOS)
    canvas.alpha_composite(base)

    layers = layers_from_config(user.avatar_config or {})
    if layers:
        rows = (
            (
                await db.execute(
                    select(AvatarAccessory).where(
                        AvatarAccessory.slug.in_([layer.accessory for layer in layers]),
                        AvatarAccessory.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_slug = {row.slug: row for row in rows}
        storage = get_storage(settings or get_settings())

        # Back to front, so a frame sits over shoulders over head.
        order = {
            AccessorySlot.HEAD: 0,
            AccessorySlot.EYES: 1,
            AccessorySlot.SHOULDERS: 2,
            AccessorySlot.FRAME: 3,
        }
        for layer in sorted(
            layers,
            key=lambda item: order.get(getattr(by_slug.get(item.accessory), "slot", None), 9),
        ):
            accessory = by_slug.get(layer.accessory)
            if accessory is None:
                # Disabled mid-event, or deleted. The avatar renders without it
                # rather than failing — art going missing is not the player's
                # problem to see as an error.
                continue
            try:
                chunks = [chunk async for chunk in storage.stream(accessory.image_key)]
                _place(canvas, Image.open(io.BytesIO(b"".join(chunks))), layer)
            except (StorageUnavailable, OSError) as exc:
                logger.warning("avatar.accessory_unavailable", slug=accessory.slug, error=str(exc))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def invalidate(user: User) -> None:
    """Drop the cached composite so the next request re-renders it.

    Called when the recipe changes underneath the cache — a new class, a new
    achievement, an edited config. Cheaper and far harder to get wrong than
    re-rendering eagerly at every call site that might have changed something.
    """
    user.avatar_blob = None


async def rendered_for(db: AsyncSession, user: User, *, settings: Settings | None = None) -> bytes:
    """The cached composite, rendering and caching it if it is not there."""
    if user.avatar_blob is not None:
        return user.avatar_blob

    composite = await render(db, user, settings=settings)
    user.avatar_blob = composite
    user.avatar_updated_at = datetime.now(UTC)
    return composite


async def invalidate_all(db: AsyncSession) -> None:
    """Drop every cached composite.

    A blunt instrument on purpose. Accessory art changing is rare and
    setup-time, and working out exactly who was wearing the piece costs more
    than letting the avatars re-render once, lazily, as they are next asked for.
    """
    from sqlalchemy import update

    await db.execute(update(User).values(avatar_blob=None))
