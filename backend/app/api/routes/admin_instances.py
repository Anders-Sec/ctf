"""Staff/admin surface for container templates and live instances (spec 009).

Templates are authored by admins and reviewed like app code (the images are ours,
never player-supplied). The instance list fills the container panel spec 006's
dashboard left as a placeholder, and force-teardown is the lever for when
something running needs to stop now.
"""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Admin, AppSettings, DbSession, Staff, get_orchestrator
from app.errors import AppError, NotFoundError
from app.models.challenge import Challenge
from app.models.instance import (
    LIVE_STATUSES,
    ChallengeInstance,
    ContainerTemplate,
    InstanceProtocol,
)
from app.models.team import Team
from app.models.user import User
from app.schemas.instances import (
    AdminInstanceResponse,
    CreateTemplateRequest,
    TemplateResponse,
)
from app.services.identity import record_audit
from app.services.instances import launcher

router = APIRouter(prefix="/admin", tags=["admin-instances"])


class TcpNotSupported(AppError):
    status_code = 400
    code = "tcp_not_supported"
    message = "Only HTTP challenges are supported. A raw-TCP target cannot be authorised."


class TemplateInUse(AppError):
    status_code = 409
    code = "template_in_use"
    message = "This template still has running instances. Tear them down first."


def _template_response(template: ContainerTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=template.id,
        name=template.name,
        image=template.image,
        image_tag=template.image_tag,
        container_port=template.container_port,
        protocol=template.protocol.value,
        ttl_seconds=template.ttl_seconds,
        injects_answer=template.injects_answer,
    )


@router.get("/templates")
async def list_templates(db: DbSession, current: Staff) -> list[TemplateResponse]:
    templates = (
        (await db.execute(select(ContainerTemplate).order_by(ContainerTemplate.name)))
        .scalars()
        .all()
    )
    return [_template_response(t) for t in templates]


@router.post("/templates", status_code=201)
async def create_template(
    payload: CreateTemplateRequest, request: Request, db: DbSession, current: Admin
) -> TemplateResponse:
    if payload.protocol != InstanceProtocol.HTTP.value:
        # Decision 3: refuse at save rather than launch something unauthorisable.
        raise TcpNotSupported

    template = ContainerTemplate(
        name=payload.name,
        image=payload.image,
        image_tag=payload.image_tag,
        container_port=payload.container_port,
        protocol=InstanceProtocol.HTTP,
        ttl_seconds=payload.ttl_seconds,
        injects_answer=payload.injects_answer,
        readiness_path=payload.readiness_path,
        cpu_limit=payload.cpu_limit,
        memory_limit=payload.memory_limit,
    )
    db.add(template)
    await db.flush()
    await record_audit(
        db,
        action="container_template.create",
        target_type="container_template",
        target_id=template.id,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    return _template_response(template)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID, request: Request, db: DbSession, current: Admin
) -> None:
    template = await db.get(ContainerTemplate, template_id)
    if template is None:
        raise NotFoundError("No such template.")

    # Only a *live* instance blocks deletion: yanking a template out from under a
    # running container would orphan it. Terminal instances and any challenges
    # still pointing at it are detached automatically (the FKs are ON DELETE SET
    # NULL), so their history survives without the now-gone template.
    live = await db.scalar(
        select(func.count())
        .select_from(ChallengeInstance)
        .where(
            ChallengeInstance.template_id == template_id,
            ChallengeInstance.status.in_(LIVE_STATUSES),
        )
    )
    if live:
        raise TemplateInUse

    await db.delete(template)
    await record_audit(
        db,
        action="container_template.delete",
        target_type="container_template",
        target_id=template_id,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/instances")
async def list_instances(db: DbSession, current: Staff) -> list[AdminInstanceResponse]:
    """Everything live, newest first, with owners and ages."""
    rows = (
        (
            await db.execute(
                select(ChallengeInstance)
                .where(ChallengeInstance.status.in_(LIVE_STATUSES))
                .order_by(ChallengeInstance.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _instance_response(db, instance) for instance in rows]


@router.delete("/instances/{instance_id}", status_code=204)
async def force_teardown(
    instance_id: UUID, request: Request, db: DbSession, settings: AppSettings, current: Admin
) -> None:
    instance = await db.get(ChallengeInstance, instance_id)
    if instance is None:
        raise NotFoundError("No such instance.")
    await launcher.destroy(db, settings, get_orchestrator(request), instance)
    await record_audit(
        db,
        action="challenge_instance.force_teardown",
        target_type="challenge_instance",
        target_id=instance_id,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )


async def _instance_response(
    db: AsyncSession, instance: ChallengeInstance
) -> AdminInstanceResponse:
    title = await db.scalar(select(Challenge.title).where(Challenge.id == instance.challenge_id))
    return AdminInstanceResponse(
        id=instance.id,
        challenge_id=instance.challenge_id,
        challenge_title=title or "(unknown)",
        status=instance.status,
        owner_label=await _owner_label(db, instance),
        connection_url=instance.connection_url,
        created_at=instance.created_at,
        expires_at=instance.expires_at,
        error=instance.last_error,
    )


async def _owner_label(db: AsyncSession, instance: ChallengeInstance) -> str:
    if instance.owner_team_id is not None:
        name = await db.scalar(select(Team.name).where(Team.id == instance.owner_team_id))
        return f"party: {name or instance.owner_team_id}"
    name = await db.scalar(select(User.display_name).where(User.id == instance.owner_user_id))
    return f"player: {name or instance.owner_user_id}"
