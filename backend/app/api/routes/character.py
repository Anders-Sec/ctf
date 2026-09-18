"""Character sheet endpoints (spec 015, 016).

``/character/me`` is the player's own full sheet — total XP, overall level and
progress, per-skill breakdown, board rank, and class (with the System AI's
suggested-class nudge). ``PUT /character/class`` sets the caller's own class.
``/character/{user_id}`` is the public view of another player: identity, overall
level, skill levels, and class.
"""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import DbSession, Player, RedisClient, ScoreboardViewer
from app.errors import NotFoundError
from app.models.user import User, UserStatus
from app.schemas.character import (
    AbilityResponse,
    CharacterSheetResponse,
    ClassResponse,
    PartyBriefResponse,
    PublicAchievementResponse,
    PublicAchievementsResponse,
    PublicCharacterResponse,
    SetClassRequest,
    SkillRowResponse,
    ZoneSolvesResponse,
)
from app.schemas.notifications import (
    AchievementResponse,
    AchievementsResponse,
    StarResponse,
)
from app.services import achievements as achievement_service
from app.services import character as character_service
from app.services import classes as class_service
from app.services import narrator, scoreboard_cache

router = APIRouter(prefix="/character", tags=["character"])

# Reading a sheet is gated on `ScoreboardViewer`, not `Player`.
#
# `require_play` goes false the moment the event ends, which took the character
# sheet — and with it spec 068's ending, which reads this very endpoint — down
# at the buzzer. `require_scoreboard` already makes the argument this needs:
# "once the event ends, play is closed but the scoreboard stays readable — the
# final standings are the point of the whole exercise and must not vanish."
#
# A player's own record of their five days is the same kind of thing. The one
# *write* here, choosing a class, stays on `Player`.


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
        rarity=getattr(character_class.rarity, "value", character_class.rarity),
    )


def _sheet_response(sheet, rank: int | None, suggestion=None) -> CharacterSheetResponse:
    return CharacterSheetResponse(
        user_id=sheet.user_id,
        display_name=sheet.display_name,
        has_avatar=sheet.has_avatar,
        total_xp=sheet.total_xp,
        level=sheet.level,
        xp_into_level=sheet.xp_into_level,
        xp_to_next=sheet.xp_to_next,
        rank=rank,
        abilities=[AbilityResponse(**vars(a)) for a in sheet.abilities],
        skills=[SkillRowResponse(**vars(s)) for s in sheet.skills],
        character_class=_class_response(sheet.character_class),
        class_unlocked=sheet.class_unlocked,
        class_unlock_level=sheet.class_unlock_level,
        party=(
            PartyBriefResponse(id=sheet.party.id, name=sheet.party.name) if sheet.party else None
        ),
        equipped_title=sheet.equipped_title,
        suggested_class=(_class_response(suggestion.character_class) if suggestion else None),
        suggested_class_line=(
            narrator.class_suggestion(suggestion.reason, suggestion.character_class.name)
            if suggestion
            else None
        ),
    )


@router.get("/me")
async def my_character(
    db: DbSession, redis: RedisClient, current: ScoreboardViewer
) -> CharacterSheetResponse:
    sheet = await character_service.build_sheet(db, current.user)
    return _sheet_response(
        sheet,
        await _rank_of(db, redis, sheet.user_id),
        await class_service.suggest_class(db, current.user.id),
    )


@router.put("/class")
async def set_my_class(
    payload: SetClassRequest, db: DbSession, redis: RedisClient, current: Player
) -> CharacterSheetResponse:
    """Set or clear the caller's own class, then hand back the refreshed sheet."""
    await character_service.set_class(db, current.user, payload.class_id)
    await achievement_service.evaluate(
        db, current.user.id, achievement_service.CLASS, achievement_service.PLATFORM, redis=redis
    )
    sheet = await character_service.build_sheet(db, current.user)
    return _sheet_response(
        sheet,
        await _rank_of(db, redis, sheet.user_id),
        await class_service.suggest_class(db, current.user.id),
    )


@router.get("/classes")
async def list_classes(db: DbSession, current: ScoreboardViewer) -> list[ClassResponse]:
    """The roster this player may pick from — **unlocked classes only**.

    A class they have not earned is absent entirely, not greyed and not counted:
    024 makes the roster a mystery, and a total would give the game away.
    """
    return [_class_response(c) for c in await class_service.available_classes(db, current.user.id)]


@router.get("/achievements")
async def my_achievements(db: DbSession, current: ScoreboardViewer) -> AchievementsResponse:
    """The full roster, unearned ones redacted, plus the rarest this player holds."""
    rows = await achievement_service.roster_for(db, current.user.id)
    rarest = await achievement_service.rarest_held(db, current.user.id)
    return AchievementsResponse(
        earned=sum(1 for r in rows if r.earned),
        total=len(rows),
        items=[AchievementResponse(**vars(r)) for r in rows],
        rarest=[AchievementResponse(**vars(r)) for r in rarest],
    )


@router.get("/stars")
async def my_stars(db: DbSession, current: ScoreboardViewer) -> list[StarResponse]:
    """Bosses this player has beaten, biggest fight first."""
    return [
        StarResponse(**vars(star))
        for star in await achievement_service.stars_for(db, current.user.id)
    ]


@router.get("/{user_id}/achievements")
async def public_achievements(
    user_id: UUID, db: DbSession, current: ScoreboardViewer
) -> PublicAchievementsResponse:
    """Somebody else's trophy case (spec 061 §4).

    Only what they earned, no descriptions, and **a secret the viewer has not
    earned themselves arrives with no name and no rarity** — redacted here rather
    than blurred in CSS, so there is nothing to read in devtools.
    """
    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotFoundError("No such player.")

    roster = await achievement_service.public_roster_for(db, user_id, current.user.id)
    return PublicAchievementsResponse(
        earned=roster.earned,
        secret_count=roster.secret_count,
        items=[PublicAchievementResponse(**vars(row)) for row in roster.items],
        rarest=[PublicAchievementResponse(**vars(row)) for row in roster.rarest],
    )


@router.get("/{user_id}")
async def public_character(
    user_id: UUID, db: DbSession, redis: RedisClient, current: ScoreboardViewer
) -> PublicCharacterResponse:
    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotFoundError("No such player.")

    sheet = await character_service.build_sheet(db, user)
    zones = await character_service.zone_solves(db, user_id)
    return PublicCharacterResponse(
        user_id=sheet.user_id,
        display_name=sheet.display_name,
        has_avatar=sheet.has_avatar,
        level=sheet.level,
        abilities=[AbilityResponse(**vars(a)) for a in sheet.abilities],
        # Undiscovered skills are omitted entirely rather than placeholdered:
        # there is nothing to tease a stranger with.
        skills=[SkillRowResponse(**vars(s)) for s in sheet.skills if s.discovered],
        character_class=_class_response(sheet.character_class),
        # Null for anybody the board does not hold. Staff are excluded from it by
        # design, and "no rank" is the honest answer for them — every other field
        # below is computed directly and is correct for anybody.
        rank=await _rank_of(db, redis, user_id),
        party=(
            PartyBriefResponse(id=sheet.party.id, name=sheet.party.name) if sheet.party else None
        ),
        equipped_title=sheet.equipped_title,
        skills_total=len(sheet.skills),
        stars=[
            StarResponse(**vars(star)) for star in await achievement_service.stars_for(db, user_id)
        ],
        # Derived from the same grouped query, so the count and the breakdown
        # cannot disagree.
        solve_count=sum(zone.solves for zone in zones),
        zones=[ZoneSolvesResponse(**vars(zone)) for zone in zones],
    )
