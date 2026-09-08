"""Character sheet endpoints (spec 015).

``/character/me`` is the player's own full sheet — total XP, overall level and
progress, per-skill breakdown, and board rank. ``/character/{user_id}`` is the
public view of another player: identity, overall level and skill levels.
"""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import DbSession, Player, RedisClient
from app.errors import NotFoundError
from app.models.user import User, UserStatus
from app.schemas.character import (
    CharacterSheetResponse,
    PublicCharacterResponse,
    PublicSkillResponse,
    SkillSliceResponse,
)
from app.services import character as character_service
from app.services import scoreboard_cache

router = APIRouter(prefix="/character", tags=["character"])


async def _rank_of(db: DbSession, redis: RedisClient, user_id: UUID) -> int | None:
    payload = await scoreboard_cache.refresh(db, redis)
    row = next((r for r in payload["players"] if r["user_id"] == str(user_id)), None)
    return row["rank"] if row else None


@router.get("/me")
async def my_character(
    db: DbSession, redis: RedisClient, current: Player
) -> CharacterSheetResponse:
    sheet = await character_service.build_sheet(db, current.user)
    return CharacterSheetResponse(
        user_id=sheet.user_id,
        display_name=sheet.display_name,
        has_avatar=sheet.has_avatar,
        total_xp=sheet.total_xp,
        level=sheet.level,
        xp_into_level=sheet.xp_into_level,
        xp_to_next=sheet.xp_to_next,
        rank=await _rank_of(db, redis, sheet.user_id),
        skills=[SkillSliceResponse(**vars(s)) for s in sheet.skills],
    )


@router.get("/{user_id}")
async def public_character(
    user_id: UUID, db: DbSession, current: Player
) -> PublicCharacterResponse:
    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotFoundError("No such player.")

    sheet = await character_service.build_sheet(db, user)
    return PublicCharacterResponse(
        user_id=sheet.user_id,
        display_name=sheet.display_name,
        has_avatar=sheet.has_avatar,
        level=sheet.level,
        skills=[
            PublicSkillResponse(skill_id=s.skill_id, name=s.name, level=s.level)
            for s in sheet.skills
        ],
    )
