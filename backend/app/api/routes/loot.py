"""Loot boxes: the inventory, opening one, and wearing the result (spec 038)."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import AppSettings, DbSession, Player, RedisClient
from app.schemas.auth import MessageResponse
from app.schemas.loot import (
    EquipRequest,
    HeldTitleResponse,
    LootBoxResponse,
    OpenedResponse,
)
from app.services import loot as loot_service

router = APIRouter(prefix="/loot", tags=["loot"])


@router.get("/boxes")
async def my_boxes(db: DbSession, current: Player) -> list[LootBoxResponse]:
    """Unopened boxes, oldest first."""
    from sqlalchemy import select

    from app.models.notification import Achievement

    boxes = await loot_service.inventory(db, current.user.id)
    names = dict(
        (
            await db.execute(
                select(Achievement.id, Achievement.name).where(
                    Achievement.id.in_([b.achievement_id for b in boxes] or [None])
                )
            )
        ).all()
    )
    return [
        LootBoxResponse(
            id=box.id,
            box_type=box.box_type.value,
            rarity=box.rarity.value,
            achievement_name=names.get(box.achievement_id, ""),
            created_at=box.created_at,
        )
        for box in boxes
    ]


@router.post("/boxes/{box_id}/open")
async def open_box(
    box_id: UUID,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    current: Player,
) -> OpenedResponse:
    """Open a box.

    Idempotent — the item is written to the box, so a second call returns the
    same title rather than rerolling it.
    """
    opened = await loot_service.open_box(
        db, current.user.id, box_id, settings=settings, redis=redis
    )
    return OpenedResponse(**vars(opened))


@router.get("/titles")
async def my_titles(db: DbSession, current: Player) -> list[HeldTitleResponse]:
    """Titles this player holds, rarest first."""
    rows = await loot_service.collection(db, current.user.id)
    return [
        HeldTitleResponse(
            item_id=item.id,
            title=item.title,
            rarity=box.rarity.value,
            box_type=box.box_type.value,
            generated=item.generated,
            equipped=current.user.equipped_title_id == item.id,
        )
        for box, item in rows
    ]


@router.put("/equipped")
async def equip_title(payload: EquipRequest, db: DbSession, current: Player) -> MessageResponse:
    """Wear one title, or none."""
    await loot_service.equip(db, current.user.id, payload.item_id)
    return MessageResponse(message="Title updated.")
