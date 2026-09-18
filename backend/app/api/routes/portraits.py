"""Building a portrait (spec 074).

The contract that matters: this router accepts **trait keys and nothing else**.
There is no field anywhere in these payloads that carries prompt text, and
``AvatarTrait.prompt_fragment`` is never serialised out. A request that tries to
smuggle prose in gets it ignored by pydantic and then refused by
``resolve_traits``, which only knows how to look keys up.
"""

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import ActiveUser, DbSession
from app.errors import NotFoundError
from app.models.avatar_trait import AvatarCandidate, AvatarJob, AvatarTrait, JobState, TraitAxis
from app.models.user import User
from app.schemas.portraits import (
    AxisOut,
    BuilderOut,
    CandidateOut,
    JobOut,
    StartJobRequest,
    TraitOut,
)
from app.services import image_client, portraits

router = APIRouter(prefix="/portraits", tags=["portraits"])


async def _current(db: DbSession, current: ActiveUser) -> User:
    user = await db.get(User, current.user.id)
    assert user is not None
    return user


@router.get("/builder", response_model=BuilderOut)
async def builder(request: Request, db: DbSession, current: ActiveUser) -> BuilderOut:
    """The choices, the budget, and whether the host is even up.

    ``available`` is what the frontend hides the whole feature behind: when the
    host is dark the entry point is simply absent, rather than present and
    failing (spec 074 §7). Everything spec 073 built carries on regardless.
    """
    settings = request.app.state.settings

    rows = (
        (
            await db.execute(
                select(AvatarTrait)
                .where(AvatarTrait.enabled.is_(True))
                .order_by(AvatarTrait.display_order)
            )
        )
        .scalars()
        .all()
    )

    by_axis: dict[str, list[TraitOut]] = {}
    for row in rows:
        # Note what is *not* here: prompt_fragment. The prompt engineering stays
        # on the server, and a response carrying it would defeat the design.
        by_axis.setdefault(row.axis.value, []).append(TraitOut(key=row.key, label=row.label))

    user = await _current(db, current)
    # Defaults this axis to the player's real class, which is what ties a
    # portrait to progression rather than to a costume box.
    default_class: str | None = None
    if user.character_class_id:
        from app.models.character_class import CharacterClass

        name = (
            await db.execute(
                select(CharacterClass.name).where(CharacterClass.id == user.character_class_id)
            )
        ).scalar_one_or_none()
        if name:
            default_class = next(
                (row.key for row in rows if row.axis == TraitAxis.CLASS_LOOK and row.label == name),
                None,
            )

    return BuilderOut(
        available=image_client.available(settings),
        remaining=await portraits.remaining(db, settings, user.id),
        candidates_per_job=settings.image_candidates,
        default_class_look=default_class,
        axes=[AxisOut(axis=axis.value, options=by_axis.get(axis.value, [])) for axis in TraitAxis],
    )


def _job_out(job: AvatarJob, candidates: list[AvatarCandidate]) -> JobOut:
    return JobOut(
        id=job.id,
        state=job.state,
        error=job.error,
        candidates=[CandidateOut(id=row.id, seed=row.seed) for row in candidates],
    )


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_job(
    payload: StartJobRequest, request: Request, db: DbSession, current: ActiveUser
) -> JobOut:
    """Queue a portrait job and run it.

    Run inline for now rather than through a worker: one GPU, a hard
    concurrency limit of one in the client, and a job that takes a few seconds.
    A second player's request waits on the client's own in-flight check and gets
    a `busy` back rather than piling onto the card. If that stops being good
    enough the seam is here, in this one function.
    """
    settings = request.app.state.settings
    user = await _current(db, current)

    job = await portraits.start(db, settings, user, payload.traits)
    await db.commit()

    await portraits.run(db, settings, job)
    await db.commit()

    rows = (
        (await db.execute(select(AvatarCandidate).where(AvatarCandidate.job_id == job.id)))
        .scalars()
        .all()
    )
    return _job_out(job, list(rows))


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, db: DbSession, current: ActiveUser) -> JobOut:
    job = await db.get(AvatarJob, job_id)
    # Somebody else's job is not found rather than forbidden: the distinction
    # would confirm it exists.
    if job is None or job.user_id != current.user.id:
        raise NotFoundError("No such job.")

    rows = (
        (await db.execute(select(AvatarCandidate).where(AvatarCandidate.job_id == job.id)))
        .scalars()
        .all()
    )
    return _job_out(job, list(rows))


@router.get("/candidates/{candidate_id}/image")
async def candidate_image(
    candidate_id: UUID, request: Request, db: DbSession, current: ActiveUser
) -> Response:
    """One candidate's PNG. Only ever to the player who asked for it."""
    candidate = await db.get(AvatarCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("No such portrait.")
    job = await db.get(AvatarJob, candidate.job_id)
    if job is None or job.user_id != current.user.id:
        raise NotFoundError("No such portrait.")

    etag = f'"{hashlib.sha256(candidate.image).hexdigest()[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(
        content=candidate.image,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "private, max-age=3600"},
    )


@router.post("/candidates/{candidate_id}/choose", response_model=JobOut)
async def choose_candidate(candidate_id: UUID, db: DbSession, current: ActiveUser) -> JobOut:
    """Adopt one, and drop the rest of the grid."""
    candidate = await db.get(AvatarCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("No such portrait.")
    job = await db.get(AvatarJob, candidate.job_id)
    if job is None or job.user_id != current.user.id:
        raise NotFoundError("No such portrait.")

    user = await _current(db, current)
    await portraits.choose(db, user, job, candidate_id)
    await db.commit()

    return _job_out(job, [candidate])


@router.get("/jobs", response_model=list[JobOut])
async def my_jobs(db: DbSession, current: ActiveUser) -> list[JobOut]:
    """The most recent job, so a reloaded page finds its grid again."""
    jobs = (
        (
            await db.execute(
                select(AvatarJob)
                .where(AvatarJob.user_id == current.user.id)
                .order_by(AvatarJob.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    if not jobs:
        return []

    rows = (
        (
            await db.execute(
                select(AvatarCandidate).where(AvatarCandidate.job_id.in_([job.id for job in jobs]))
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[UUID, list[AvatarCandidate]] = {}
    for row in rows:
        grouped.setdefault(row.job_id, []).append(row)

    return [_job_out(job, grouped.get(job.id, [])) for job in jobs if job.state == JobState.DONE]
