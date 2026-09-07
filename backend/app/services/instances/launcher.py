"""Launching, polling, extending and destroying a player's instance.

This is the orchestration logic 008 designed, against the `InstanceOrchestrator`
interface — so all of it is tested with the fake and none of it imports a
Kubernetes library. The two things worth reading carefully are the per-owner cap
(serialized by a row lock, not a stale count) and the state transitions in
`refresh`, which is what the poll endpoint calls.
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, NotFoundError
from app.logging import get_logger
from app.models.challenge import Challenge, ChallengeState
from app.models.instance import (
    LIVE_STATUSES,
    ChallengeInstance,
    ContainerTemplate,
    InstanceProtocol,
    InstanceStatus,
)
from app.models.team import Team
from app.models.user import User
from app.services.instances.manifests import InstanceSpec
from app.services.instances.orchestrator import InstanceOrchestrator
from app.services.user_cache import load_active_team

logger = get_logger(__name__)

#: Env var name the demo image (and real challenge images) read the per-instance
#: answer from. Baked into the target at launch.
ANSWER_ENV = "INSTANCE_ANSWER"


class InstancesUnavailable(AppError):
    status_code = 503
    code = "instances_unavailable"
    message = "Live challenges are not available right now."


class NotAContainerChallenge(AppError):
    status_code = 400
    code = "not_a_container_challenge"
    message = "This challenge has no live container."


class InstanceCapReached(AppError):
    status_code = 409
    code = "instance_cap_reached"
    message = "You already have as many live challenges as you can run at once."


class InstanceCapacityUnavailable(AppError):
    status_code = 503
    code = "instance_capacity_unavailable"
    message = "There is no capacity for a new instance right now. Try again shortly."


def _dns_name() -> str:
    """A DNS-1035 label: starts with a letter, lowercase, short. Also the subdomain."""
    return "dm-" + secrets.token_hex(8)


def _generate_answer() -> str:
    return "flag{" + secrets.token_hex(12) + "}"


async def _owner(db: AsyncSession, user: User) -> tuple[Team | None, User]:
    """A party if the player is in one, else the lone player. Sharing a live
    target is exactly the division of labour a party is for (008 Decision 4)."""
    team = await load_active_team(db, user.id)
    return team, user


async def _live_for_owner(
    db: AsyncSession, team: Team | None, user: User
) -> list[ChallengeInstance]:
    condition = (
        ChallengeInstance.owner_team_id == team.id
        if team is not None
        else ChallengeInstance.owner_user_id == user.id
    )
    return list(
        (
            await db.execute(
                select(ChallengeInstance).where(
                    condition, ChallengeInstance.status.in_(LIVE_STATUSES)
                )
            )
        )
        .scalars()
        .all()
    )


async def _lock_owner(db: AsyncSession, team: Team | None, user: User) -> None:
    """Serialize concurrent launches for the same owner, so two clicks cannot both
    pass a stale cap count. Same row-lock mechanism as the last party seat."""
    if team is not None:
        await db.execute(select(Team.id).where(Team.id == team.id).with_for_update())
    else:
        await db.execute(select(User.id).where(User.id == user.id).with_for_update())


async def launch(
    db: AsyncSession,
    settings: Settings,
    orchestrator: InstanceOrchestrator,
    challenge_id: UUID,
    user: User,
    now: datetime | None = None,
) -> ChallengeInstance:
    now = now or datetime.now(UTC)
    if not settings.instances_configured:
        raise InstancesUnavailable

    challenge, template = await _load_container_challenge(db, challenge_id, now)
    team, owner_user = await _owner(db, user)

    await _lock_owner(db, team, owner_user)
    live = await _live_for_owner(db, team, owner_user)

    # Idempotent for the same challenge: a second launch returns the one they have
    # rather than a duplicate that also eats the cap.
    for existing in live:
        if existing.challenge_id == challenge.id:
            return existing

    if len(live) >= settings.instance_max_per_owner:
        raise InstanceCapReached

    instance = ChallengeInstance(
        challenge_id=challenge.id,
        template_id=template.id,
        owner_team_id=team.id if team is not None else None,
        owner_user_id=None if team is not None else owner_user.id,
        k8s_name=_dns_name(),
        status=InstanceStatus.PENDING,
        generated_answer=_generate_answer() if template.injects_answer else None,
        expires_at=now + timedelta(seconds=template.ttl_seconds),
    )
    db.add(instance)
    await db.flush()

    spec = _spec_for(settings, instance, template)
    host, authorise = _exposure(settings, instance)
    try:
        result = await orchestrator.launch(
            spec,
            expose_ingress=settings.instance_http_mode == "ingress",
            host=host,
            authorise_url=authorise,
        )
    except Exception as exc:  # noqa: BLE001 - the cluster refusing is not a 500
        instance.status = InstanceStatus.FAILED
        instance.last_error = type(exc).__name__
        await db.flush()
        logger.warning("instance_launch_failed", extra={"error_type": type(exc).__name__})
        raise InstanceCapacityUnavailable from exc

    if result.node_port is not None:
        instance.node_port = result.node_port
    if result.ready:
        _mark_running(settings, instance)
    await db.flush()

    logger.info(
        "instance_launched",
        extra={"instance": instance.k8s_name, "challenge_id": str(challenge.id)},
    )
    return instance


async def refresh(
    db: AsyncSession,
    settings: Settings,
    orchestrator: InstanceOrchestrator,
    instance: ChallengeInstance,
) -> ChallengeInstance:
    """The poll target. Advances pending → running/failed from the cluster's view."""
    if instance.status != InstanceStatus.PENDING:
        return instance

    state = await orchestrator.status(settings.kube_namespace, instance.k8s_name)
    if not state.exists:
        instance.status = InstanceStatus.FAILED
        instance.last_error = "pod disappeared"
    elif state.error:
        instance.status = InstanceStatus.FAILED
        instance.last_error = state.error
    elif state.ready:
        _mark_running(settings, instance)
    await db.flush()
    return instance


async def destroy(
    db: AsyncSession,
    settings: Settings,
    orchestrator: InstanceOrchestrator,
    instance: ChallengeInstance,
    *,
    status: InstanceStatus = InstanceStatus.DESTROYED,
    now: datetime | None = None,
) -> None:
    """Idempotent teardown. A cluster 404 is success — the goal is 'gone'."""
    await orchestrator.destroy(settings.kube_namespace, instance.k8s_name)
    instance.status = status
    instance.destroyed_at = now or datetime.now(UTC)
    await db.flush()


async def extend(
    db: AsyncSession, settings: Settings, instance: ChallengeInstance, now: datetime | None = None
) -> ChallengeInstance:
    now = now or datetime.now(UTC)
    if instance.status not in LIVE_STATUSES:
        raise NotFoundError("That instance is no longer running.")
    # Add the window to whatever is left, never replace it: a player who extends
    # a fresh 60-minute instance must not have it cut to the 30-minute grant.
    base = max(now, instance.expires_at)
    instance.expires_at = base + timedelta(seconds=settings.instance_extend_seconds)
    await db.flush()
    return instance


async def find_for_owner(
    db: AsyncSession, challenge_id: UUID, team: Team | None, user: User
) -> ChallengeInstance | None:
    """The player's live instance for a challenge, if any — the GET/DELETE target."""
    live = await _live_for_owner(db, team, user)
    return next((i for i in live if i.challenge_id == challenge_id), None)


def _mark_running(settings: Settings, instance: ChallengeInstance) -> None:
    instance.status = InstanceStatus.RUNNING
    instance.connection_url = _connection_url(settings, instance)


def _connection_url(settings: Settings, instance: ChallengeInstance) -> str:
    if settings.instance_http_mode == "ingress":
        return f"https://{instance.k8s_name}.{settings.instance_base_domain}"
    return f"http://{settings.instance_base_domain}:{instance.node_port}"


def _exposure(settings: Settings, instance: ChallengeInstance) -> tuple[str | None, str | None]:
    if settings.instance_http_mode != "ingress":
        return None, None
    host = f"{instance.k8s_name}.{settings.instance_base_domain}"
    authorise = "http://ctf-backend.ctf.svc.cluster.local:8000/api/instances/authorise"
    return host, authorise


def _spec_for(
    settings: Settings, instance: ChallengeInstance, template: ContainerTemplate
) -> InstanceSpec:
    env = dict(template.env)
    if template.injects_answer and instance.generated_answer:
        env[ANSWER_ENV] = instance.generated_answer

    owner_kind = "team" if instance.owner_team_id else "user"
    owner_id = str(instance.owner_team_id or instance.owner_user_id)

    return InstanceSpec(
        name=instance.k8s_name,
        namespace=settings.kube_namespace,
        image=f"{template.image}:{template.image_tag}",
        container_port=template.container_port,
        owner_kind=owner_kind,
        owner_id=owner_id,
        env=env,
        cpu_request=template.cpu_request,
        cpu_limit=template.cpu_limit,
        memory_request=template.memory_request,
        memory_limit=template.memory_limit,
        runtime_class=template.runtime_class or settings.instance_runtime_class,
        egress_policy=template.egress_policy,
        egress_cidrs=list(template.egress_cidrs),
        readiness_path=template.readiness_path,
        image_pull_secret=settings.instance_image_pull_secret,
    )


async def _load_container_challenge(
    db: AsyncSession, challenge_id: UUID, now: datetime
) -> tuple[Challenge, ContainerTemplate]:
    challenge = (
        await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ).scalar_one_or_none()
    # 404, not 400, for a challenge the player cannot see — same non-oracle rule
    # as the rest of spec 003.
    if challenge is None or challenge.effective_state(now) != ChallengeState.PUBLISHED:
        raise NotFoundError("No such challenge.")
    if challenge.container_template_id is None:
        raise NotAContainerChallenge

    template = await db.get(ContainerTemplate, challenge.container_template_id)
    if template is None:
        raise NotAContainerChallenge
    if template.protocol != InstanceProtocol.HTTP:
        # Phase 1 is HTTP only (decision 3); a tcp template should never have been
        # saved, but refuse rather than launch something unauthorisable.
        raise NotAContainerChallenge
    return challenge, template


async def count_live(db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count(ChallengeInstance.id)).where(
                ChallengeInstance.status.in_(LIVE_STATUSES)
            )
        )
    ) or 0
