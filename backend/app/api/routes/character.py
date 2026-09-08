"""Character sheet endpoints (spec 015, 016).

``/character/me`` is the player's own full sheet — total XP, overall level and
progress, per-skill breakdown, board rank, and class (with the System AI's
suggested-class nudge). ``PUT /character/class`` sets the caller's own class.
``/character/{user_id}`` is the public view of another player: identity, overall
level, skill levels, and class.
"""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import DbSession, Player, RedisClient
from app.errors import NotFoundError
from app.models.user import User, UserStatus
from app.schemas.character import (
    CharacterSheetResponse,
    ClassResponse,
    PublicCharacterResponse,
    PublicSkillResponse,
    SetClassRequest,
    SkillSliceResponse,
    SuggestedClassResponse,
)
from app.services import character as character_service
from app.services import scoreboard_cache

router = APIRouter(prefix="/character", tags=["character"])


async def _rank_of(db: DbSession, redis: RedisClient, user_id: UUID) -> int | None:
    payload = await scoreboard_cache.refresh(db, redis)
    row = next((r for r in payload["players"] if r["user_id"] == str(user_id)), None)
    return row["rank"] if row else None


def _class_response(character_class) -> ClassResponse | None:
    if character_class is None:
        return None
    return ClassResponse(
        id=character_class.id,
        name=character_class.name,
        description=character_class.description,
    )


def _sheet_response(sheet, rank: int | None) -> CharacterSheetResponse:
    suggested = (
        SuggestedClassResponse(**vars(sheet.suggested_class)) if sheet.suggested_class else None
    )
    return CharacterSheetResponse(
        user_id=sheet.user_id,
        display_name=sheet.display_name,
        has_avatar=sheet.has_avatar,
        total_xp=sheet.total_xp,
        level=sheet.level,
        xp_into_level=sheet.xp_into_level,
        xp_to_next=sheet.xp_to_next,
        rank=rank,
        skills=[SkillSliceResponse(**vars(s)) for s in sheet.skills],
        character_class=_class_response(sheet.character_class),
        suggested_class=suggested,
        class_unlocked=sheet.class_unlocked,
        class_unlock_level=sheet.class_unlock_level,
    )


@router.get("/me")
async def my_character(
    db: DbSession, redis: RedisClient, current: Player
) -> CharacterSheetResponse:
    sheet = await character_service.build_sheet(db, current.user)
    return _sheet_response(sheet, await _rank_of(db, redis, sheet.user_id))


@router.put("/class")
async def set_my_class(
    payload: SetClassRequest, db: DbSession, redis: RedisClient, current: Player
) -> CharacterSheetResponse:
    """Set or clear the caller's own class, then hand back the refreshed sheet."""
    await character_service.set_class(db, current.user, payload.class_id)
    sheet = await character_service.build_sheet(db, current.user)
    return _sheet_response(sheet, await _rank_of(db, redis, sheet.user_id))


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
        character_class=_class_response(sheet.character_class),
    )
