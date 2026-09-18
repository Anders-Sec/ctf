"""Choosing an avatar (spec 073 §6).

Gated on ``ActiveUser`` rather than ``Player`` on purpose. An avatar is
identity, not play: picking one before the doors open is a good way to spend the
wait, and spec 068's ending still renders rosters after the event is over. Spec
068 found every character route 403-ing at the buzzer for exactly this reason —
the same mistake is not worth making twice.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import ActiveUser, DbSession
from app.models.avatar import AvatarAccessory
from app.models.user import AvatarSource, User
from app.schemas.avatar import AccessoryOut, AvatarIn, AvatarOut, LayerOut
from app.services.avatars import (
    Layer,
    config_from_layers,
    invalidate,
    layers_from_config,
    unlocked_slugs,
    validate_layers,
)
from app.services.sigils import describe_sigil

router = APIRouter(prefix="/avatar", tags=["avatar"])


async def _current(db: DbSession, current: ActiveUser) -> User:
    user = await db.get(User, current.user.id)
    assert user is not None  # the gate already proved they exist
    return user


@router.get("/accessories", response_model=list[AccessoryOut])
async def list_accessories(db: DbSession, current: ActiveUser) -> list[AccessoryOut]:
    """Everything there is, with what you hold marked.

    Locked ones are listed rather than withheld — unlike a challenge title or an
    achievement's description, an accessory's existence is not a secret, and
    seeing the wizard hat you have not earned is the motivation.
    """
    rows = (
        (
            await db.execute(
                select(AvatarAccessory)
                .where(AvatarAccessory.enabled.is_(True))
                .order_by(AvatarAccessory.display_order, AvatarAccessory.name)
            )
        )
        .scalars()
        .all()
    )
    held = await unlocked_slugs(db, current.user.id)

    return [
        AccessoryOut(
            slug=row.slug,
            name=row.name,
            description=row.description,
            slot=row.slot,
            rarity=row.rarity,
            unlocked=row.slug in held,
            unlock_kind=row.unlock_kind,
            unlock_ref=row.unlock_ref,
            anchor_x=row.anchor_x,
            anchor_y=row.anchor_y,
            anchor_scale=row.anchor_scale,
            anchor_rotation=row.anchor_rotation,
        )
        for row in rows
    ]


def _view(user: User) -> AvatarOut:
    return AvatarOut(
        source=user.avatar_source,
        layers=[
            LayerOut(
                accessory=layer.accessory,
                x=layer.x,
                y=layer.y,
                scale=layer.scale,
                rotation=layer.rotation,
            )
            for layer in layers_from_config(user.avatar_config or {})
        ],
        description=describe_sigil(str(user.id)),
        has_photo=user.avatar_base is not None,
    )


@router.get("/me", response_model=AvatarOut)
async def get_my_avatar(db: DbSession, current: ActiveUser) -> AvatarOut:
    return _view(await _current(db, current))


@router.put("/me", response_model=AvatarOut)
async def set_my_avatar(payload: AvatarIn, db: DbSession, current: ActiveUser) -> AvatarOut:
    """Set the base and the layers.

    Validation is server-side against the derived unlock set: what the client
    believes it owns is not evidence (specs 018, 028). A locked accessory is
    **refused** rather than quietly dropped, so nobody ends up believing they
    equipped something they did not.
    """
    user = await _current(db, current)

    layers = [
        Layer(
            accessory=item.accessory,
            x=item.x,
            y=item.y,
            scale=item.scale,
            rotation=item.rotation,
        )
        for item in payload.layers
    ]
    await validate_layers(db, user.id, layers)

    source = payload.source
    if source in (AvatarSource.ENTRA, AvatarSource.GENERATED) and user.avatar_base is None:
        # Asking for a photo there is no photo for. The crest is the honest
        # answer rather than an error nobody can act on.
        source = AvatarSource.SIGIL

    user.avatar_source = source
    user.avatar_config = config_from_layers(layers)
    await invalidate(user)
    await db.commit()
    await db.refresh(user)

    return _view(user)


@router.post("/me/reset", response_model=AvatarOut)
async def reset_my_avatar(db: DbSession, current: ActiveUser) -> AvatarOut:
    """Back to the bare crest."""
    user = await _current(db, current)
    user.avatar_source = AvatarSource.SIGIL
    user.avatar_config = {}
    await invalidate(user)
    await db.commit()
    await db.refresh(user)
    return _view(user)
