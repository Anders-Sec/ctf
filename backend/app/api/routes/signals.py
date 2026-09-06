"""Anti-cheat signals and the player timeline.

Staff-gated rather than admin-gated: organisers are exactly the people who
should be reviewing this, and none of it changes anything. Nothing here is ever
visible to players — telling someone they have been flagged turns a statistical
coincidence into an accusation before a human has looked at it.
"""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession, Staff
from app.errors import NotFoundError
from app.models.signal import SignalDismissal
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.signals import (
    DismissSignalRequest,
    PlayerTimelineResponse,
    SignalsResponse,
)
from app.services import signals as signal_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["signals"])


@router.get("/signals")
async def list_signals(db: DbSession, settings: AppSettings, current: Staff) -> SignalsResponse:
    results = await signal_service.compute(db, settings)
    return SignalsResponse(
        counts={name: len(findings) for name, findings in results.items()},
        findings={
            name: [finding.to_dict() for finding in findings] for name, findings in results.items()
        },
    )


@router.get("/signals/{signal_type}")
async def signal_detail(
    signal_type: str, db: DbSession, settings: AppSettings, current: Staff
) -> SignalsResponse:
    results = await signal_service.compute(db, settings, only=signal_type)
    if signal_type not in results:
        raise NotFoundError("No such signal type.")
    return SignalsResponse(
        counts={signal_type: len(results[signal_type])},
        findings={signal_type: [f.to_dict() for f in results[signal_type]]},
    )


@router.post("/signals/dismiss")
async def dismiss_signal(
    payload: DismissSignalRequest,
    request: Request,
    db: DbSession,
    current: Staff,
) -> MessageResponse:
    """Record that someone looked at this and concluded it was fine."""
    existing = await db.scalar(
        select(SignalDismissal).where(
            SignalDismissal.signal_type == payload.signal_type,
            SignalDismissal.subject_key == payload.subject_key,
        )
    )
    if existing is None:
        db.add(
            SignalDismissal(
                signal_type=payload.signal_type,
                subject_key=payload.subject_key,
                note=payload.note,
                dismissed_by_user_id=current.user.id,
            )
        )
        await db.flush()

    await record_audit(
        db,
        action="signal.dismiss",
        target_type="signal",
        actor_user_id=current.user.id,
        reason=payload.note,
        meta={"signal_type": payload.signal_type, "subject_key": payload.subject_key},
        request_id=getattr(request.state, "request_id", None),
    )
    return MessageResponse(message="Dismissed.")


@router.get("/players/{user_id}/timeline")
async def player_timeline(user_id: UUID, db: DbSession, current: Staff) -> PlayerTimelineResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such player.")

    return PlayerTimelineResponse(
        user_id=user.id,
        display_name=user.display_name,
        events=await signal_service.player_timeline(db, user_id),
    )
