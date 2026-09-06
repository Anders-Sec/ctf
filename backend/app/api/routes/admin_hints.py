"""Admin CRUD for hints.

Reads are open to organizers, so staff can see what a hint says without being
able to change what it costs. Writes require admin.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from app.api.deps import Admin, DbSession, Staff
from app.errors import ConflictError, NotFoundError
from app.models.challenge import Challenge
from app.models.hint import Hint, HintUnlock
from app.schemas.admin_hints import (
    AdminHintResponse,
    CreateHintRequest,
    UpdateHintRequest,
)
from app.schemas.auth import MessageResponse
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/challenges/{challenge_id}/hints", tags=["admin-hints"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _require_challenge(db: DbSession, challenge_id: UUID) -> None:
    if await db.scalar(select(Challenge.id).where(Challenge.id == challenge_id)) is None:
        raise NotFoundError("No such challenge.")


async def _load(db: DbSession, challenge_id: UUID, hint_id: UUID) -> Hint:
    hint = (
        await db.execute(select(Hint).where(Hint.id == hint_id, Hint.challenge_id == challenge_id))
    ).scalar_one_or_none()
    if hint is None:
        raise NotFoundError("No such hint.")
    return hint


async def _unlock_count(db: DbSession, hint_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(HintUnlock).where(HintUnlock.hint_id == hint_id)
        )
    ) or 0


def _response(hint: Hint, unlock_count: int) -> AdminHintResponse:
    return AdminHintResponse(
        id=hint.id,
        challenge_id=hint.challenge_id,
        title=hint.title,
        body=hint.body,
        cost=hint.cost,
        display_order=hint.display_order,
        prerequisite_hint_id=hint.prerequisite_hint_id,
        available_after=hint.available_after,
        unlock_count=unlock_count,
    )


@router.get("")
async def list_hints(challenge_id: UUID, db: DbSession, current: Staff) -> list[AdminHintResponse]:
    await _require_challenge(db, challenge_id)
    hints = (
        (
            await db.execute(
                select(Hint)
                .where(Hint.challenge_id == challenge_id)
                .order_by(Hint.display_order, Hint.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_response(hint, await _unlock_count(db, hint.id)) for hint in hints]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_hint(
    challenge_id: UUID,
    payload: CreateHintRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminHintResponse:
    await _require_challenge(db, challenge_id)

    if payload.prerequisite_hint_id is not None:
        # A prerequisite on another challenge's hint would be unsatisfiable
        # from this challenge's page.
        await _load(db, challenge_id, payload.prerequisite_hint_id)

    hint = Hint(challenge_id=challenge_id, **payload.model_dump())
    db.add(hint)
    await db.flush()

    await record_audit(
        db,
        action="hint.create",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        # Title and cost only: the audit log is readable by organizers and is
        # not the place to reproduce hint text.
        meta={"hint_id": str(hint.id), "title": hint.title, "cost": hint.cost},
        request_id=_request_id(request),
    )
    return _response(hint, 0)


@router.patch("/{hint_id}")
async def update_hint(
    challenge_id: UUID,
    hint_id: UUID,
    payload: UpdateHintRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminHintResponse:
    hint = await _load(db, challenge_id, hint_id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("prerequisite_hint_id") == hint_id:
        raise ConflictError("A hint cannot require itself.", code="hint_prerequisite_cycle")

    for field, value in changes.items():
        setattr(hint, field, value)
    await db.flush()

    await record_audit(
        db,
        action="hint.update",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"hint_id": str(hint_id), **{k: str(v) for k, v in changes.items() if k != "body"}},
        request_id=_request_id(request),
    )
    return _response(hint, await _unlock_count(db, hint_id))


@router.delete("/{hint_id}")
async def delete_hint(
    challenge_id: UUID,
    hint_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    hint = await _load(db, challenge_id, hint_id)

    unlocks = await _unlock_count(db, hint_id)
    if unlocks:
        # People paid for it. Refunding is a score adjustment an admin makes
        # deliberately, not a side effect of tidying up.
        raise ConflictError(
            f"{unlocks} players have paid for this hint. It cannot be deleted.",
            code="hint_has_unlocks",
        )

    await db.delete(hint)
    await record_audit(
        db,
        action="hint.delete",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"hint_id": str(hint_id), "title": hint.title},
        request_id=_request_id(request),
    )
    await db.flush()
    return MessageResponse(message="Hint removed.")
