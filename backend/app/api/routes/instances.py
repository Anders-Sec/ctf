"""Player-facing live-instance endpoints (spec 009).

Provisioning is slow, so this is the one deliberately asynchronous corner of the
app: POST returns `pending` immediately and the client polls GET until `running`
or `failed`. Everything is gated on `Player` (approved account, event running),
the same as flag submission.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.api.deps import AppSettings, DbSession, Player, get_orchestrator
from app.errors import NotFoundError
from app.schemas.instances import InstanceResponse
from app.services.cookies import ACCESS_COOKIE
from app.services.instances import launcher
from app.services.instances.orchestrator import InstanceOrchestrator
from app.services.user_cache import load_active_team

router = APIRouter(tags=["instances"])


def _orch(request: Request) -> InstanceOrchestrator:
    return get_orchestrator(request)


def _response(instance) -> InstanceResponse:  # noqa: ANN001 - ChallengeInstance row
    return InstanceResponse(
        id=instance.id,
        challenge_id=instance.challenge_id,
        status=instance.status,
        connection_url=instance.connection_url,
        expires_at=instance.expires_at,
        error=instance.last_error,
    )


@router.post("/challenges/{challenge_id}/instance", status_code=201)
async def launch_instance(
    challenge_id: UUID,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> InstanceResponse:
    instance = await launcher.launch(
        db, settings, _orch(request), challenge_id, current.user, datetime.now(UTC)
    )
    return _response(instance)


@router.get("/challenges/{challenge_id}/instance")
async def get_instance(
    challenge_id: UUID,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> InstanceResponse:
    team = await load_active_team(db, current.user.id)
    instance = await launcher.find_for_owner(db, challenge_id, team, current.user)
    if instance is None:
        raise NotFoundError("You have no instance for this challenge.")
    instance = await launcher.refresh(db, settings, _orch(request), instance)
    return _response(instance)


@router.delete("/challenges/{challenge_id}/instance", status_code=204)
async def destroy_instance(
    challenge_id: UUID,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> None:
    team = await load_active_team(db, current.user.id)
    instance = await launcher.find_for_owner(db, challenge_id, team, current.user)
    if instance is None:
        raise NotFoundError("You have no instance for this challenge.")
    await launcher.destroy(db, settings, _orch(request), instance)


@router.get("/instances/authorise/{instance_name}")
async def authorise_instance(
    instance_name: str, request: Request, db: DbSession, settings: AppSettings
) -> Response:
    """The ingress auth-url subrequest. Returns only 200 (allow) or 401 (deny).

    The instance name comes from the URL path -- each instance's Ingress points
    auth-url at its own name -- so this needs no snippet annotation. Not gated by
    the normal auth dependency: it is a GET subrequest carrying the browser's
    cookies, no CSRF, and it must never raise -- an exception the ingress reads as
    a 500 could fail open, so it fails closed to 401.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    allowed = await launcher.authorise(db, settings, token, instance_name)
    return Response(status_code=200 if allowed else 401)


@router.post("/challenges/{challenge_id}/instance/extend")
async def extend_instance(
    challenge_id: UUID,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> InstanceResponse:
    team = await load_active_team(db, current.user.id)
    instance = await launcher.find_for_owner(db, challenge_id, team, current.user)
    if instance is None:
        raise NotFoundError("You have no instance for this challenge.")
    instance = await launcher.extend(db, settings, instance)
    return _response(instance)
