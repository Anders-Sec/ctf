"""Admin: the accessory roster and the moderation backstop (spec 073 §8).

Two jobs. The roster is setup work — upload art, set anchors, enable or disable
a piece — and follows the memory note that admin tools are setup tools, so there
is no mid-event friction designed in. The second job is the one that matters
mid-event: **reset a player's avatar**, which is one button, and much easier to
have already built than to need and not have.
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, File, Request, UploadFile, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession, Staff
from app.errors import NotFoundError
from app.models.avatar import AvatarAccessory
from app.models.user import AvatarSource, User
from app.schemas.auth import MessageResponse
from app.schemas.avatar import (
    AccessoryAdminOut,
    CreateAccessoryRequest,
    UpdateAccessoryRequest,
)
from app.services.accessory_roster import seed
from app.services.artifacts import ArtifactTooLarge
from app.services.avatars import invalidate, invalidate_all
from app.services.identity import record_audit
from app.services.storage import get_storage

router = APIRouter(prefix="/admin/avatar", tags=["admin-avatar"])

#: Art is small and square. A generous ceiling that still refuses a video
#: somebody dropped in by accident.
MAX_ART_BYTES = 2 * 1024 * 1024


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _out(row: AvatarAccessory) -> AccessoryAdminOut:
    return AccessoryAdminOut.model_validate(row)


@router.get("/accessories", response_model=list[AccessoryAdminOut])
async def list_accessories(db: DbSession, _: Staff) -> list[AccessoryAdminOut]:
    rows = (
        (
            await db.execute(
                select(AvatarAccessory).order_by(
                    AvatarAccessory.display_order, AvatarAccessory.name
                )
            )
        )
        .scalars()
        .all()
    )
    return [_out(row) for row in rows]


@router.post("/accessories", response_model=AccessoryAdminOut, status_code=status.HTTP_201_CREATED)
async def create_accessory(
    payload: CreateAccessoryRequest, request: Request, db: DbSession, current: Admin
) -> AccessoryAdminOut:
    row = AvatarAccessory(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        slot=payload.slot,
        rarity=payload.rarity,
        image_key=f"accessories/{payload.slug}.png",
        unlock_kind=payload.unlock_kind,
        unlock_ref=payload.unlock_ref,
        anchor_x=payload.anchor_x,
        anchor_y=payload.anchor_y,
        anchor_scale=payload.anchor_scale,
        anchor_rotation=payload.anchor_rotation,
        display_order=payload.display_order,
    )
    db.add(row)
    await db.flush()
    await record_audit(
        db,
        action="avatar.accessory.create",
        target_type="avatar_accessory",
        target_id=row.id,
        actor_user_id=current.user.id,
        meta={"slug": row.slug},
        request_id=_request_id(request),
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.patch("/accessories/{accessory_id}", response_model=AccessoryAdminOut)
async def update_accessory(
    accessory_id: UUID,
    payload: UpdateAccessoryRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AccessoryAdminOut:
    row = await db.get(AvatarAccessory, accessory_id)
    if row is None:
        raise NotFoundError("No such accessory.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    await record_audit(
        db,
        action="avatar.accessory.update",
        target_type="avatar_accessory",
        target_id=row.id,
        actor_user_id=current.user.id,
        meta={"slug": row.slug},
        request_id=_request_id(request),
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/accessories/{accessory_id}/art", response_model=AccessoryAdminOut)
async def upload_art(
    accessory_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
    file: UploadFile = File(...),
) -> AccessoryAdminOut:
    """Put the PNG behind an accessory.

    Transparency is the whole point of the format here, so this refuses
    anything that is not a PNG rather than accepting a JPEG that would
    composite as an opaque square over somebody's face.
    """
    row = await db.get(AvatarAccessory, accessory_id)
    if row is None:
        raise NotFoundError("No such accessory.")

    data = await file.read()
    if len(data) > MAX_ART_BYTES:
        raise ArtifactTooLarge("That image is too large. Two megabytes is plenty.")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ArtifactTooLarge(
            "Accessory art has to be a PNG — it needs a transparent background.",
            code="not_a_png",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    key = f"accessories/{row.slug}-{uuid.uuid4().hex[:8]}.png"
    await get_storage(request.app.state.settings).put(key, data, "image/png")
    row.image_key = key

    # Every avatar wearing it is now stale.
    await invalidate_all(db)

    await record_audit(
        db,
        action="avatar.accessory.art",
        target_type="avatar_accessory",
        target_id=row.id,
        actor_user_id=current.user.id,
        meta={"slug": row.slug, "key": key},
        request_id=_request_id(request),
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/accessories/reseed", response_model=MessageResponse)
async def reseed(request: Request, db: DbSession, current: Admin) -> MessageResponse:
    """Re-run the authored roster, adding anything missing.

    Never overwrites: an anchor tuned during setup survives.
    """
    added = await seed(db)
    await record_audit(
        db,
        action="avatar.roster.reseed",
        target_type="avatar_accessory",
        actor_user_id=current.user.id,
        meta={"added": added},
        request_id=_request_id(request),
    )
    await db.commit()
    return MessageResponse(message=f"{added} added.")


@router.post("/users/{user_id}/reset", response_model=MessageResponse)
async def reset_player_avatar(
    user_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    """The moderation backstop: put a player back on their bare crest.

    Spec 074 will need this for a generated portrait that comes out wrong. It
    is here now because it is one button, and the wrong time to build it is the
    moment somebody needs it.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    user.avatar_source = AvatarSource.SIGIL
    user.avatar_config = {}
    # The base goes too: a reset that left an offending portrait one click away
    # from being re-selected would not be a reset.
    user.avatar_base = None
    await invalidate(user)

    await record_audit(
        db,
        action="avatar.reset",
        target_type="user",
        target_id=user_id,
        actor_user_id=current.user.id,
        request_id=_request_id(request),
    )
    await db.commit()
    return MessageResponse(message="That player is back on their crest.")
