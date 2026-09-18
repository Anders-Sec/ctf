"""The player's notification feed, REST and WebSocket (spec 028)."""

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import DbSession, Player
from app.db import get_sessionmaker
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.redis import get_redis
from app.schemas.auth import MessageResponse
from app.schemas.notifications import (
    DismissRequest,
    NotificationFeed,
    NotificationResponse,
)
from app.services import notifications as notification_service
from app.services.capabilities import resolve_capabilities
from app.services.cookies import ACCESS_COOKIE
from app.services.security import TokenError, access_token_subject
from app.services.user_cache import load_user

router = APIRouter(tags=["notifications"])


def _response(view) -> NotificationResponse:
    return NotificationResponse(
        id=view.id,
        kind=view.kind,
        title=view.title,
        body=view.body,
        link=view.link,
        read=view.read,
        created_at=view.created_at,
    )


@router.get("/notifications")
async def feed(db: DbSession, current: Player) -> NotificationFeed:
    """The backlog, newest first. The record, whether or not a socket was open."""
    return NotificationFeed(
        unread=await notification_service.unread_count(db, current.user.id),
        items=[_response(v) for v in await notification_service.backlog(db, current.user.id)],
    )


@router.post("/notifications/read")
async def mark_all_read(db: DbSession, current: Player) -> MessageResponse:
    changed = await notification_service.mark_read(db, current.user.id)
    return MessageResponse(message=f"Marked {changed} read.")


@router.post("/notifications/{notification_id}/read")
async def mark_one_read(notification_id: UUID, db: DbSession, current: Player) -> MessageResponse:
    await notification_service.mark_read(db, current.user.id, notification_id)
    return MessageResponse(message="Marked read.")


@router.post("/notifications/dismiss")
async def dismiss_many(payload: DismissRequest, db: DbSession, current: Player) -> MessageResponse:
    """Clear everything, or everything of the given kinds (spec 065 §4).

    Scoped by kind so "clear all" on one inbox tab cannot take the other tab's
    rows with it — clearing the event news must not throw away a player's own
    record of what they achieved.
    """
    changed = await notification_service.dismiss(db, current.user.id, kinds=payload.kinds)
    return MessageResponse(message=f"Cleared {changed}.")


@router.post("/notifications/{notification_id}/dismiss")
async def dismiss_one(notification_id: UUID, db: DbSession, current: Player) -> MessageResponse:
    await notification_service.dismiss(db, current.user.id, notification_id=notification_id)
    return MessageResponse(message="Cleared.")


@router.websocket("/ws/notifications")
async def notification_socket(websocket: WebSocket) -> None:
    """Push this player's notifications as they happen.

    Subscribed to one channel per recipient rather than a shared one: fanning
    every notification to every connection and filtering client-side would put
    one player's messages on another player's wire.
    """
    settings = websocket.app.state.settings
    sessionmaker = get_sessionmaker(settings)
    redis = get_redis(settings)

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
        if not capabilities.play:
            await websocket.close(code=4403, reason="not a player")
            return

        backlog = await notification_service.backlog(session, user.id, unread_only=True)

    await websocket.accept()
    # Unread first, so a reconnect is self-healing the way the scoreboard is.
    for view in reversed(backlog):
        await websocket.send_text(json.dumps(notification_service.payload_of(view)))

    pubsub = redis.pubsub()
    await pubsub.subscribe(notification_service.channel_for(user.id))
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            await websocket.send_text(data.decode() if isinstance(data, bytes) else str(data))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(notification_service.channel_for(user.id))
            await pubsub.aclose()


# The announce endpoint moved to `admin_announcements` in spec 054, which gave
# it a history, a read count and scheduling. Leaving a copy here would have been
# two routers claiming one path, with FastAPI picking whichever registered
# first — so it is gone rather than deprecated.
