"""Scoreboard endpoints, REST and WebSocket."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import DbSession, RedisClient, ScoreboardViewer, Staff
from app.db import get_sessionmaker
from app.logging import get_logger
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.redis import get_redis
from app.schemas.scoreboard import (
    MyStandingResponse,
    PartyPanelResponse,
    PlayerBoardResponse,
    TeamBoardResponse,
)
from app.services import admin_scoreboard, party_panel, scoreboard_cache
from app.services.capabilities import resolve_capabilities
from app.services.cookies import ACCESS_COOKIE
from app.services.security import TokenError, access_token_subject
from app.services.user_cache import load_user

logger = get_logger(__name__)

router = APIRouter(tags=["scoreboard"])


async def _payload(db: DbSession, redis: RedisClient) -> dict:
    """The boards as a player may see them — no XP on either (spec 059 §2)."""
    return scoreboard_cache.public_view(await scoreboard_cache.refresh(db, redis))


@router.get("/scoreboard/players")
async def player_board(
    db: DbSession,
    redis: RedisClient,
    current: ScoreboardViewer,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PlayerBoardResponse:
    payload = await _payload(db, redis)
    rows = payload["players"]
    return PlayerBoardResponse(
        total=len(rows),
        generated_at=payload["generated_at"],
        entries=rows[offset : offset + limit],
    )


@router.get("/scoreboard/teams")
async def team_board(
    db: DbSession,
    redis: RedisClient,
    current: ScoreboardViewer,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TeamBoardResponse:
    payload = await _payload(db, redis)
    rows = payload["teams"]
    return TeamBoardResponse(
        total=len(rows),
        generated_at=payload["generated_at"],
        entries=rows[offset : offset + limit],
    )


@router.get("/scoreboard/me")
async def my_standing(
    db: DbSession, redis: RedisClient, current: ScoreboardViewer
) -> MyStandingResponse:
    """Own rank and party rank, for a compact header."""
    payload = await _payload(db, redis)
    user_id = str(current.user.id)

    mine = next((row for row in payload["players"] if row["user_id"] == user_id), None)
    team_id = mine["team_id"] if mine else None
    party = (
        next((row for row in payload["teams"] if row["team_id"] == team_id), None)
        if team_id
        else None
    )

    return MyStandingResponse(
        rank=mine["rank"] if mine else None,
        level=mine["level"] if mine else 1,
        player_count=len(payload["players"]),
        team_rank=party["rank"] if party else None,
        team_level=party["level"] if party else None,
        team_count=len(payload["teams"]),
    )


@router.get("/scoreboard/teams/{team_id}")
async def party_panel_detail(
    team_id: UUID, db: DbSession, redis: RedisClient, current: ScoreboardViewer
) -> PartyPanelResponse:
    """Who a party is (spec 059 §5).

    Opened from either board. A party has no page of its own and does not need
    one — and duplicating a fraction of the character sheet in a panel would be a
    second thing to keep true, which is why a *player* row links through instead.
    """
    return PartyPanelResponse(**await party_panel.detail(db, redis, team_id))


@router.get("/admin/scoreboard")
async def admin_board(db: DbSession, redis: RedisClient, current: Staff) -> dict:
    """Both boards in full (spec 051 §3).

    Not gated on the event running, unlike the public board: settling a
    placement happens after the doors close, which is exactly when that gate
    would shut.
    """
    return await admin_scoreboard.board(db, redis)


@router.websocket("/ws/scoreboard")
async def scoreboard_socket(websocket: WebSocket) -> None:
    """Push both boards on every change.

    Each message is a whole board rather than a diff, so a client that misses
    messages — or drops out entirely — is made whole simply by reconnecting.
    """
    settings = websocket.app.state.settings
    sessionmaker = get_sessionmaker(settings)
    redis = get_redis(settings)

    # The handshake authenticates from the same cookie as every other request.
    token = websocket.cookies.get(ACCESS_COOKIE)
    if not token:
        await websocket.close(code=4401, reason="not authenticated")
        return

    try:
        user_id = access_token_subject(settings, token)
    except TokenError:
        await websocket.close(code=4401, reason="not authenticated")
        return

    async with sessionmaker() as session:
        user = await load_user(session, user_id)
        if user is None:
            await websocket.close(code=4401, reason="not authenticated")
            return

        event = await session.get(EventConfig, EVENT_CONFIG_ID)
        capabilities = resolve_capabilities(user, event, datetime.now(UTC))
        if not capabilities.view_scoreboard:
            await websocket.close(code=4403, reason="scoreboard unavailable")
            return

        # The public view, same as the REST boards: the socket is a board
        # surface too, and every later push already arrives stripped because the
        # channel carries the public payload.
        initial = scoreboard_cache.public_view(await scoreboard_cache.refresh(session, redis))

    await websocket.accept()
    queue = scoreboard_cache.broadcaster.subscribe()

    try:
        # Send the current state immediately, so a client is never staring at an
        # empty board waiting for someone else to score.
        await websocket.send_json(initial)
        while True:
            payload = await queue.get()
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info("scoreboard_socket_closed", extra={"error_type": type(exc).__name__})
    finally:
        scoreboard_cache.broadcaster.unsubscribe(queue)
