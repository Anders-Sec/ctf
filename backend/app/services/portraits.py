"""Generating portraits: the queue, the budget, and the prompt (spec 074 §5).

The rule this file exists to enforce: **a prompt can only be built from trait
keys that resolved against the database**. There is no path from a request body
to the model that skips ``resolve_traits``, which is what makes "players cannot
write prompts" a property of the code rather than a promise in a spec.

One GPU and 200 players means a request is a *job*: it queues, it produces four
candidates to choose between, and the finished grid arrives through the inbox so
nobody has to sit on the page.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError
from app.logging import get_logger
from app.models.avatar_trait import AvatarCandidate, AvatarJob, AvatarTrait, JobState, TraitAxis
from app.models.user import AvatarSource, User
from app.services import image_client
from app.services.avatars import invalidate
from app.services.trait_roster import assemble_prompt

logger = get_logger(__name__)


class GenerationUnavailable(AppError):
    status_code = 503
    code = "generation_unavailable"
    message = "Portrait generation is not available right now."


class UnknownTrait(AppError):
    status_code = 422
    code = "unknown_trait"
    message = "That is not one of the choices."


class OutOfGenerations(AppError):
    status_code = 429
    code = "out_of_generations"
    message = "You have used your portraits. Loot grants more."


class JobInFlight(AppError):
    status_code = 409
    code = "job_in_flight"
    message = "You already have a portrait being made."


@dataclass(frozen=True)
class Resolved:
    """Trait keys that exist, and the fragments they mean."""

    keys: dict[str, str]
    fragments: list[str]


#: The order fragments are joined in. Subject first, then what they are wearing,
#: then how it is lit and drawn — which reads to the model roughly the way it
#: reads to a person.
_ORDER = [
    TraitAxis.ANCESTRY,
    TraitAxis.CLASS_LOOK,
    TraitAxis.GARB,
    TraitAxis.HEADWEAR,
    TraitAxis.EXPRESSION,
    TraitAxis.SETTING,
    TraitAxis.PALETTE,
    TraitAxis.ART_STYLE,
]


async def resolve_traits(db: AsyncSession, chosen: dict[str, str]) -> Resolved:
    """Turn ``{axis: key}`` into fragments, refusing anything not on the list.

    The only way to reach the model. An axis that is missing is simply left out
    of the prompt — a portrait with no stated setting is fine — but a key that
    does not exist is an error, never silently dropped, because silently
    dropping it would produce a portrait the player did not ask for.
    """
    if not chosen:
        return Resolved(keys={}, fragments=[])

    rows = (
        (
            await db.execute(
                select(AvatarTrait).where(
                    AvatarTrait.enabled.is_(True),
                    AvatarTrait.key.in_(list(chosen.values())),
                )
            )
        )
        .scalars()
        .all()
    )
    by_pair = {(row.axis.value, row.key): row for row in rows}

    keys: dict[str, str] = {}
    fragments: list[str] = []
    for axis in _ORDER:
        key = chosen.get(axis.value)
        if key is None:
            continue
        row = by_pair.get((axis.value, key))
        if row is None:
            raise UnknownTrait(f"No such {axis.value}: {key}")
        keys[axis.value] = key
        fragments.append(row.prompt_fragment)

    unknown_axes = set(chosen) - {axis.value for axis in _ORDER}
    if unknown_axes:
        raise UnknownTrait(f"No such axis: {sorted(unknown_axes)[0]}")

    return Resolved(keys=keys, fragments=fragments)


async def generations_used(db: AsyncSession, user_id: UUID) -> int:
    """Jobs that actually reached the model.

    A job the host refused because it was switched off does not count: a budget
    spent on our own downtime would be an unpleasant surprise.
    """
    return (
        await db.execute(
            select(func.count())
            .select_from(AvatarJob)
            .where(AvatarJob.user_id == user_id, AvatarJob.state != JobState.FAILED)
        )
    ).scalar_one()


async def remaining(db: AsyncSession, settings: Settings, user_id: UUID) -> int:
    """How many portraits this player has left.

    Budget plus grants. A reroll of the same traits costs one, otherwise the
    grid is a slot machine.
    """
    from app.models.notification import LootBox

    granted = (
        await db.execute(
            select(func.count()).select_from(LootBox).where(LootBox.user_id == user_id)
        )
    ).scalar_one()
    # Loot is the tap: every box opened is one more portrait, on top of the
    # starting allowance.
    allowance = settings.image_budget + int(granted)
    return max(0, allowance - await generations_used(db, user_id))


async def start(
    db: AsyncSession, settings: Settings, user: User, chosen: dict[str, str]
) -> AvatarJob:
    """Queue a job. Does not generate — ``run`` does, off the request path."""
    if not image_client.available(settings):
        raise GenerationUnavailable()

    in_flight = (
        await db.execute(
            select(func.count())
            .select_from(AvatarJob)
            .where(
                AvatarJob.user_id == user.id,
                AvatarJob.state.in_([JobState.QUEUED, JobState.RUNNING]),
            )
        )
    ).scalar_one()
    if in_flight:
        raise JobInFlight()

    if await remaining(db, settings, user.id) <= 0:
        raise OutOfGenerations()

    resolved = await resolve_traits(db, chosen)
    job = AvatarJob(user_id=user.id, traits=resolved.keys, state=JobState.QUEUED)
    db.add(job)
    await db.flush()
    return job


async def run(db: AsyncSession, settings: Settings, job: AvatarJob) -> AvatarJob:
    """Do the work: four seeds, four candidates, one job.

    Called from the queue rather than the request. Every failure lands on the
    job as a coarse reason rather than escaping as a 500 — the host being off
    is an expected state, not an exception.
    """
    job.state = JobState.RUNNING
    await db.flush()

    resolved = await resolve_traits(db, dict(job.traits))
    prompt = assemble_prompt(resolved.fragments)

    produced = 0
    last_error: str | None = None
    for _ in range(settings.image_candidates):
        seed = random.randint(1, 2_000_000_000)
        reply = await image_client.generate(settings, prompt, seed=seed)
        if reply.ok and reply.image:
            db.add(AvatarCandidate(job_id=job.id, seed=seed, image=reply.image))
            produced += 1
        else:
            last_error = reply.error
            if reply.unavailable:
                # No point asking three more times for a host that is dark.
                break

    if produced:
        job.state = JobState.DONE
        job.error = None
    else:
        job.state = JobState.FAILED
        job.error = last_error

    # Logged with the trait keys, so a portrait that comes out wrong is
    # traceable to the exact inputs and the offending fragment can be disabled.
    logger.info(
        "avatar_job_finished",
        extra={
            "job": str(job.id),
            "state": job.state.value,
            "produced": produced,
            "traits": job.traits,
            "error": job.error,
        },
    )
    await db.flush()
    return job


async def choose(
    db: AsyncSession, user: User, job: AvatarJob, candidate_id: UUID
) -> AvatarCandidate:
    """Adopt one candidate as the avatar's base."""
    candidate = await db.get(AvatarCandidate, candidate_id)
    if candidate is None or candidate.job_id != job.id or job.user_id != user.id:
        raise UnknownTrait("No such portrait.")

    user.avatar_base = candidate.image
    user.avatar_source = AvatarSource.GENERATED
    await invalidate(user)

    # The rest of the grid goes: storing every rejected portrait of every player
    # for five days buys nothing (spec 074 §9.4).
    await db.execute(
        delete(AvatarCandidate).where(
            AvatarCandidate.job_id == job.id, AvatarCandidate.id != candidate.id
        )
    )
    await db.flush()
    return candidate


async def purge_expired(db: AsyncSession, settings: Settings) -> int:
    """Drop candidates nobody picked. Returns how many went."""
    cutoff = datetime.now(UTC) - timedelta(hours=settings.image_candidate_ttl_hours)
    result = await db.execute(delete(AvatarCandidate).where(AvatarCandidate.created_at < cutoff))
    return result.rowcount or 0
