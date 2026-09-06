"""Player-facing challenge endpoints.

Every route here is gated on `Player`, spec 002's `require_play` — approved
account, event running. An unapproved guest or a pre-event visitor reaches none
of it.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession, Player, RedisClient
from app.models.challenge import Challenge, ChallengeState
from app.models.play import Solve
from app.schemas.challenges import (
    ArtifactResponse,
    CategoryResponse,
    ChallengeDetail,
    ChallengeListItem,
    HintResponse,
    MyScoreResponse,
    SolveSummary,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    UnlockHintResponse,
)
from app.services import artifacts as artifact_service
from app.services import challenges as challenge_service
from app.services import hints as hint_service
from app.services import scoreboard_cache, scoring

router = APIRouter(tags=["challenges"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _list_item(row: dict) -> ChallengeListItem:
    challenge = row["challenge"]
    return ChallengeListItem(
        id=challenge.id,
        title=challenge.title,
        slug=challenge.slug,
        category=CategoryResponse.model_validate(challenge.category, from_attributes=True),
        difficulty=challenge.difficulty,
        state=row["effective_state"],
        locked=row["effective_state"] == ChallengeState.LOCKED,
        value=row["value"],
        solve_count=row["solve_count"],
        solved=row["solved"],
        attempts_remaining=row["attempts_remaining"],
        max_attempts=challenge.max_attempts,
        release_at=challenge.release_at,
    )


@router.get("/challenges")
async def list_challenges(db: DbSession, current: Player) -> list[ChallengeListItem]:
    rows = await challenge_service.list_for_player(db, current.user.id, datetime.now(UTC))
    return [_list_item(row) for row in rows]


@router.get("/challenges/{challenge_id}")
async def get_challenge(challenge_id: UUID, db: DbSession, current: Player) -> ChallengeDetail:
    row = await challenge_service.get_for_player(
        db, challenge_id, current.user.id, datetime.now(UTC)
    )
    challenge = row["challenge"]
    locked = row["effective_state"] == ChallengeState.LOCKED

    hints = (
        [] if locked else await hint_service.list_for_challenge(db, challenge.id, current.user.id)
    )

    return ChallengeDetail(
        **_list_item(row).model_dump(),
        # The body is withheld server-side. The client is never sent something
        # it is trusted to hide.
        body=None if locked else challenge.body,
        artifacts=[]
        if locked
        else [
            ArtifactResponse.model_validate(artifact, from_attributes=True)
            for artifact in challenge.artifacts
        ],
        hints=[_hint_response(view) for view in hints],
    )


def _hint_response(view: "hint_service.HintView") -> HintResponse:
    return HintResponse(
        id=view.hint.id,
        title=view.hint.title,
        cost=view.effective_cost,
        unlocked=view.unlocked,
        available=view.available,
        # Never sent before it is bought.
        body=view.hint.body if view.unlocked else None,
    )


@router.post("/challenges/{challenge_id}/hints/{hint_id}/unlock")
async def unlock_hint(
    challenge_id: UUID,
    hint_id: UUID,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    current: Player,
) -> UnlockHintResponse:
    """Buy a hint.

    Resolving the challenge through the player rules first means a hint on a
    locked or hidden challenge is unreachable, whatever id is supplied.
    """
    row = await challenge_service.get_for_player(
        db, challenge_id, current.user.id, datetime.now(UTC)
    )
    if row["effective_state"] == ChallengeState.LOCKED:
        raise challenge_service.ChallengeLocked

    result = await hint_service.unlock(db, hint_id, challenge_id, current.user.id)

    if result.cost_charged:
        background.add_task(scoreboard_cache.mark_dirty, redis)

    return UnlockHintResponse(
        body=result.body,
        cost_charged=result.cost_charged,
        already_unlocked=result.already_unlocked,
        new_total=await scoring.user_score(db, current.user.id),
    )


@router.post("/challenges/{challenge_id}/submit")
async def submit_answer(
    challenge_id: UUID,
    payload: SubmitAnswerRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    current: Player,
) -> SubmitAnswerResponse:
    outcome = await challenge_service.submit_answer(
        db,
        redis,
        current.user,
        challenge_id,
        payload.answer,
        ip=request.client.host if request.client else None,
        request_id=_request_id(request),
    )

    if outcome.correct and not outcome.already_solved:
        # A solve moves this player, their party, and — through decay — everyone
        # else who has solved this challenge. Queued rather than awaited: the
        # recompute must not see this transaction before it commits.
        background.add_task(scoreboard_cache.mark_dirty, redis)

    if outcome.already_solved and outcome.correct:
        message = "You have already solved this one."
    elif outcome.correct:
        message = f"Correct. {outcome.points_awarded} points."
    else:
        message = "Not quite. Try again."

    return SubmitAnswerResponse(
        correct=outcome.correct,
        already_solved=outcome.already_solved,
        points_awarded=outcome.points_awarded,
        attempts_remaining=outcome.attempts_remaining,
        message=message,
    )


@router.get("/challenges/{challenge_id}/artifacts/{artifact_id}")
async def download_artifact(
    challenge_id: UUID,
    artifact_id: UUID,
    db: DbSession,
    settings: AppSettings,
    current: Player,
) -> StreamingResponse:
    """Stream a challenge file.

    The challenge is resolved through the player visibility rules first, so a
    locked or hidden challenge's files are unreachable even with a valid
    artifact id.
    """
    row = await challenge_service.get_for_player(
        db, challenge_id, current.user.id, datetime.now(UTC)
    )
    if row["effective_state"] == ChallengeState.LOCKED:
        raise challenge_service.ChallengeLocked

    artifact = await artifact_service.get_artifact(db, challenge_id, artifact_id)

    return StreamingResponse(
        artifact_service.stream_artifact(settings, artifact),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(artifact.size_bytes),
            "X-Checksum-SHA256": artifact.checksum_sha256,
        },
    )


@router.get("/categories")
async def list_categories(db: DbSession, current: Player) -> list[CategoryResponse]:
    return [
        CategoryResponse.model_validate(category, from_attributes=True)
        for category in await challenge_service.list_categories(db)
    ]


@router.get("/me/score")
async def my_score(db: DbSession, current: Player) -> MyScoreResponse:
    rows = (
        await db.execute(
            select(Solve, Challenge)
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Solve.user_id == current.user.id)
            .order_by(Solve.submitted_at.desc())
        )
    ).all()

    challenge_ids = [challenge.id for _, challenge in rows]
    player_counts = await scoring.solve_counts_for(db, challenge_ids)
    team_counts = await scoring.team_solve_counts_for(db, challenge_ids)
    categories = {
        category.id: category.name for category in await challenge_service.list_categories(db)
    }

    solves = []
    for solve, challenge in rows:
        counts = team_counts if challenge.decay_basis.value == "teams" else player_counts
        solves.append(
            SolveSummary(
                challenge_id=challenge.id,
                title=challenge.title,
                category=categories.get(challenge.category_id, ""),
                value=scoring.challenge_value(challenge, counts.get(challenge.id, 0)),
                solved_at=solve.submitted_at,
            )
        )

    return MyScoreResponse(
        total=await scoring.user_score(db, current.user.id),
        solves=solves,
    )
