"""Launching, polling, extending and destroying a player's instance.

This is the orchestration logic 008 designed, against the `InstanceOrchestrator`
interface — so all of it is tested with the fake and none of it imports a
Kubernetes library. The two things worth reading carefully are the per-owner cap
(serialized by a row lock, not a stale count) and the state transitions in
`refresh`, which is what the poll endpoint calls.
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, NotFoundError
from app.logging import get_logger
from app.models.challenge import Challenge, ChallengeAnswer, ChallengeState, MatchType
from app.models.instance import (
    LIVE_STATUSES,
    ChallengeInstance,
    ChallengeInstanceAnswer,
    ContainerTemplate,
    InstanceProtocol,
    InstanceStatus,
)
from app.models.play import Solve
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.services.instances.manifests import InstanceSpec
from app.services.instances.orchestrator import InstanceOrchestrator
from app.services.user_cache import load_active_team

logger = get_logger(__name__)

#: Env var name a single-challenge image reads its per-instance answer from.
#: Kept from spec 009 so the demo image and anything like it is untouched.
ANSWER_ENV = "INSTANCE_ANSWER"

#: Env var a multi-challenge image reads from: a JSON object of challenge slug to
#: minted flag (spec 046). Slug-keyed because a slug survives a retitle and is
#: already the CSV's match key.
ANSWERS_ENV = "INSTANCE_ANSWERS"

#: Templates saved before the lifetime was bounded can hold a value that expires
#: an instance before the player reaches it — a zero, most likely, which is what
#: an emptied number field used to send. The schema refuses those now, but a row
#: already in the database does not re-validate itself, so a non-positive TTL is
#: treated as the configured default rather than handed to a team as a target
#: that dies on the next reconciler tick.
MIN_USABLE_TTL_SECONDS = 60

#: Length of the per-team tail, in bytes — eight hex characters. Guessing is not
#: the threat (003 rate-limits submissions); sharing is. Eight keeps a flag short
#: enough to retype off a terminal.
TAIL_BYTES = 4


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


def _mint(stem: str) -> str:
    """One challenge's flag for one instance: the authored stem, a fresh tail.

    Called once per challenge per launch, so every sibling gets a tail of its
    own. A tail shared across an instance's challenges would be worse than
    useless: the stems are the challenge titles, so a team that solved the easy
    one could type the hard one's flag without exploiting anything.
    """
    return "flag{" + stem + "_" + secrets.token_hex(TAIL_BYTES) + "}"


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


async def _served_challenges(
    db: AsyncSession, template: ContainerTemplate, challenge: Challenge, now: datetime
) -> list[Challenge]:
    """Every published challenge this instance will serve.

    One challenge for an ordinary template; all of a shared template's published
    challenges, because the container is handed its flags once at launch and
    cannot be topped up afterwards. A player is then free to work them in any
    order.
    """
    if not template.shared_instance:
        return [challenge]

    rows = (
        (await db.execute(select(Challenge).where(Challenge.container_template_id == template.id)))
        .scalars()
        .all()
    )
    published = [c for c in rows if c.effective_state(now) == ChallengeState.PUBLISHED]
    # A sibling published after this launch has no flag here; relaunching is what
    # fixes it, and the TTL makes that happen anyway.
    return published or [challenge]


async def _stems(db: AsyncSession, challenge_ids: list[UUID]) -> dict[UUID, str]:
    """Each challenge's dynamic stem, for the challenges that declare one."""
    if not challenge_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ChallengeAnswer).where(
                    ChallengeAnswer.challenge_id.in_(challenge_ids),
                    ChallengeAnswer.match_type == MatchType.DYNAMIC,
                )
            )
        )
        .scalars()
        .all()
    )
    # First rule wins if somebody has written two; display_order is the author's
    # stated preference.
    stems: dict[UUID, str] = {}
    for rule in sorted(rows, key=lambda r: (r.display_order, r.created_at)):
        stems.setdefault(rule.challenge_id, rule.value.strip())
    return stems


async def _mint_answers(
    db: AsyncSession,
    instance: ChallengeInstance,
    template: ContainerTemplate,
    challenge: Challenge,
    now: datetime,
) -> list[tuple[Challenge, ChallengeInstanceAnswer]]:
    """Mint one flag per challenge this instance serves.

    A challenge with no dynamic rule is skipped rather than given a random flag:
    it is solved by its static answer, and inventing one nobody can reach would
    turn a working challenge into an unsolvable one.
    """
    if not template.injects_answer:
        return []

    served = await _served_challenges(db, template, challenge, now)
    stems = await _stems(db, [c.id for c in served])

    minted: list[tuple[Challenge, ChallengeInstanceAnswer]] = []
    for served_challenge in served:
        stem = stems.get(served_challenge.id)
        value = _mint(stem) if stem else _generate_answer()
        row = ChallengeInstanceAnswer(
            instance_id=instance.id, challenge_id=served_challenge.id, value=value
        )
        db.add(row)
        minted.append((served_challenge, row))
    await db.flush()
    return minted


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

    # Idempotent for the same target: a second launch returns the one they have
    # rather than a duplicate that also eats the cap. For a shared template the
    # target is the *template*, so the second, third and fourth challenge in an
    # area all arrive here and get the container that is already running.
    for existing in live:
        if template.shared_instance:
            if existing.template_id == template.id:
                return existing
        elif existing.challenge_id == challenge.id:
            return existing

    if len(live) >= settings.instance_max_per_owner:
        raise InstanceCapReached

    ttl_seconds = template.ttl_seconds
    if ttl_seconds < MIN_USABLE_TTL_SECONDS:
        logger.warning(
            "template_ttl_unusable",
            extra={"template": template.name, "ttl_seconds": ttl_seconds},
        )
        ttl_seconds = settings.instance_default_ttl_seconds

    instance = ChallengeInstance(
        challenge_id=challenge.id,
        template_id=template.id,
        owner_team_id=team.id if team is not None else None,
        owner_user_id=None if team is not None else owner_user.id,
        k8s_name=_dns_name(),
        status=InstanceStatus.PENDING,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    db.add(instance)
    await db.flush()

    minted = await _mint_answers(db, instance, template, challenge, now)
    spec = _spec_for(settings, instance, template, minted)
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
        extra={
            "instance": instance.k8s_name,
            "challenge_id": str(challenge.id),
            # The lifetime this instance actually got, and from which template.
            # Without these, an instance vanishing early is indistinguishable
            # from a container crashing, and the difference took days to find.
            "template": template.name,
            "ttl_seconds": ttl_seconds,
            "expires_at": instance.expires_at.isoformat(),
        },
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
    """The player's live instance for a challenge, if any — the GET/DELETE target.

    For a shared template this finds the instance whichever of the template's
    challenges it was launched from, which is what lets a team work four
    challenges in one container (spec 046).
    """
    live = await _live_for_owner(db, team, user)
    if not live:
        return None

    challenge = await db.get(Challenge, challenge_id)
    template_id = challenge.container_template_id if challenge else None
    template = await db.get(ContainerTemplate, template_id) if template_id else None

    if template is not None and template.shared_instance:
        return next((i for i in live if i.template_id == template.id), None)
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
    # The per-instance name is appended to this base by the ingress manifest.
    authorise = "http://ctf-backend.ctf.svc.cluster.local:8000/api/instances/authorise"
    return host, authorise


def _spec_for(
    settings: Settings,
    instance: ChallengeInstance,
    template: ContainerTemplate,
    minted: list[tuple[Challenge, ChallengeInstanceAnswer]],
) -> InstanceSpec:
    env = dict(template.env)
    if len(minted) == 1:
        # A single-challenge image keeps spec 009's variable and needs to know
        # nothing about any of this.
        env[ANSWER_ENV] = minted[0][1].value
    if minted:
        env[ANSWERS_ENV] = json.dumps(
            {served.slug: answer.value for served, answer in minted}, sort_keys=True
        )

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
        tls_secret=settings.instance_tls_secret,
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


async def answer_matches(
    db: AsyncSession, challenge_id: UUID, team: Team | None, user: User, submitted: str
) -> bool:
    """Whether a submission equals *this player's own* flag for this challenge.

    The correct string is unique per instance and per challenge, so one team
    cannot pass another the answer, and solving one challenge in a shared
    container does not hand over its siblings (008 Decision 6, spec 046). A
    player with no live instance simply cannot match, which is right — there is
    nothing to have solved.
    """
    instance = await find_for_owner(db, challenge_id, team, user)
    if instance is None:
        return False

    value = await db.scalar(
        select(ChallengeInstanceAnswer.value).where(
            ChallengeInstanceAnswer.instance_id == instance.id,
            ChallengeInstanceAnswer.challenge_id == challenge_id,
        )
    )
    if not value:
        return False
    # Casefolded, as every other flag in the event is: a player who types the
    # tail in capitals has still solved it.
    return secrets.compare_digest(submitted.strip().casefold(), value.casefold())


async def shared_challenge_count(db: AsyncSession, challenge: Challenge) -> int:
    """How many *other* published challenges share this one's container.

    Zero for every ordinary template, so the player's panel is unchanged for
    everything that existed before spec 046. Only published siblings are
    counted — the number must never reveal a draft.
    """
    if challenge.container_template_id is None:
        return 0
    template = await db.get(ContainerTemplate, challenge.container_template_id)
    if template is None or not template.shared_instance:
        return 0

    now = datetime.now(UTC)
    siblings = (
        (
            await db.execute(
                select(Challenge).where(
                    Challenge.container_template_id == template.id,
                    Challenge.id != challenge.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return sum(1 for c in siblings if c.effective_state(now) == ChallengeState.PUBLISHED)


async def note_solved(
    db: AsyncSession,
    settings: Settings,
    challenge: Challenge,
    team: Team | None,
    user: User,
    now: datetime | None = None,
) -> None:
    """Start the wind-down once an owner has solved everything their container serves.

    Shortens the TTL to the grace window rather than destroying: the expiry loop
    already tears down correctly under its advisory lock, so this needs no second
    destruction path. It only ever shortens — an instance already expiring sooner
    is left alone, and a player who wants longer can still press extend.
    """
    if challenge.container_template_id is None:
        return
    template = await db.get(ContainerTemplate, challenge.container_template_id)
    if template is None or not template.shared_instance:
        return

    instance = await find_for_owner(db, challenge.id, team, user)
    if instance is None or instance.status not in LIVE_STATUSES:
        return

    now = now or datetime.now(UTC)
    served = await _served_challenges(db, template, challenge, now)

    # Solves belong to players, never to parties (spec 003), but the container
    # belongs to the party — and dividing the work is what a party is for (008
    # Decision 4). So the owner is finished when every challenge has been solved
    # by *someone currently in it*, not when one person has solved them all.
    if team is not None:
        solver_ids = list(
            (
                await db.execute(
                    select(TeamMembership.user_id).where(
                        TeamMembership.team_id == team.id,
                        TeamMembership.removed_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    else:
        solver_ids = [user.id]

    solved = set(
        (
            await db.execute(
                select(Solve.challenge_id).where(
                    Solve.user_id.in_(solver_ids),
                    Solve.challenge_id.in_([c.id for c in served]),
                )
            )
        )
        .scalars()
        .all()
    )
    if any(c.id not in solved for c in served):
        return

    deadline = now + timedelta(seconds=settings.instance_completion_grace_seconds)
    if deadline < instance.expires_at:
        instance.expires_at = deadline
        await db.flush()
        logger.info(
            "instance_completed",
            extra={"instance": instance.k8s_name, "template": template.name},
        )


async def count_live(db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count(ChallengeInstance.id)).where(
                ChallengeInstance.status.in_(LIVE_STATUSES)
            )
        )
    ) or 0


async def authorise(
    db: AsyncSession, settings: Settings, token: str | None, instance_name: str
) -> bool:
    """Whether the session behind `token` owns the instance named `instance_name`.

    The ingress calls this on every request to an instance subdomain, so ownership
    is enforced at the edge and the subdomain never has to be secret. Fails closed:
    anything unexpected is a no, never a 500 that the ingress would treat as allow.
    """
    from app.services.security import TokenError, access_token_subject
    from app.services.user_cache import load_user

    if not token:
        return False
    try:
        user_id = access_token_subject(settings, token)
    except TokenError:
        return False

    instance = (
        await db.execute(
            select(ChallengeInstance).where(
                ChallengeInstance.k8s_name == instance_name,
                ChallengeInstance.status.in_(LIVE_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if instance is None:
        return False

    if instance.owner_user_id is not None:
        return instance.owner_user_id == user_id

    # Team-owned: any current member of the owning party may reach it — sharing
    # the target is the point of a party holding it.
    user = await load_user(db, user_id)
    if user is None:
        return False
    team = await load_active_team(db, user_id)
    return team is not None and team.id == instance.owner_team_id
