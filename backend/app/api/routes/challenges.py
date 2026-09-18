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
from app.models.puzzle import PuzzleKind, PuzzleStatus
from app.schemas.challenges import (
    ArtifactResponse,
    CategoryResponse,
    ChallengeDetail,
    ChallengeListItem,
    HintResponse,
    MyScoreResponse,
    PuzzleMoveRequest,
    PuzzleSaveRequest,
    PuzzleStateResponse,
    SolveSummary,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    UnlockHintResponse,
    UnlockRequirementResponse,
)
from app.services import achievements as achievement_service
from app.services import artifacts as artifact_service
from app.services import challenges as challenge_service
from app.services import hints as hint_service
from app.services import puzzle_play, scoreboard_cache, scoring

router = APIRouter(tags=["challenges"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _requirement_response(req) -> UnlockRequirementResponse:
    """A ``RequirementView`` as JSON. The view is already player-safe — the
    evaluator filtered out anything they may not see."""
    return UnlockRequirementResponse(
        type=req.type.value,
        met=req.met,
        description=req.description,
        challenge_id=req.challenge_id,
        title=req.title,
        skill_id=req.skill_id,
        skill_name=req.skill_name,
        category_id=req.category_id,
        category_name=req.category_name,
        threshold=req.threshold,
        progress=req.progress,
    )


def _list_item(
    row: dict,
    puzzle_kind: PuzzleKind | None = None,
    puzzle_status: PuzzleStatus | None = None,
) -> ChallengeListItem:
    challenge = row["challenge"]
    locked = row["effective_state"] == ChallengeState.LOCKED
    return ChallengeListItem(
        puzzle_kind=puzzle_kind,
        puzzle_status=puzzle_status,
        id=challenge.id,
        # Withheld while sealed, exactly as `body` is (spec 062 §4.2). Sending it
        # and hiding it in CSS would be theatre — it would sit in the payload for
        # anybody who opened devtools. How big and how hard it is stays visible;
        # that is the carrot. The name is the content.
        title=None if locked else challenge.title,
        # And the slug with it: slugs are the kebab-cased title ("Port of Call"
        # → "port-of-call"), so withholding one and sending the other would hand
        # over the name in a thin disguise.
        slug=None if locked else challenge.slug,
        category=CategoryResponse.model_validate(challenge.category, from_attributes=True),
        difficulty=challenge.difficulty,
        state=row["effective_state"],
        locked=locked,
        value=row["value"],
        solve_count=row["solve_count"],
        solved=row["solved"],
        attempts_remaining=row["attempts_remaining"],
        max_attempts=challenge.max_attempts,
        release_at=challenge.release_at,
        unlock_requirements=[
            _requirement_response(req) for req in row.get("unlock_requirements", [])
        ],
    )


@router.get("/challenges")
async def list_challenges(db: DbSession, current: Player) -> list[ChallengeListItem]:
    rows = await challenge_service.list_for_player(db, current.user.id, datetime.now(UTC))

    # Two queries for the whole board rather than two per row.
    ids = [row["challenge"].id for row in rows]
    kinds = await puzzle_play.kinds_for(db, ids)
    statuses = await puzzle_play.statuses_for(db, current.user.id, ids)

    return [
        _list_item(
            row,
            kinds.get(row["challenge"].id),
            statuses.get(row["challenge"].id),
        )
        for row in rows
    ]


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

    puzzle = await puzzle_play.get_puzzle(db, challenge.id)
    session = (
        None if puzzle is None else await puzzle_play.session_for(db, current.user.id, challenge.id)
    )

    return ChallengeDetail(
        **_list_item(
            row,
            # The kind is safe on a locked challenge — "this one is a Wordle"
            # gives nothing away, and the board already says so.
            puzzle.kind if puzzle else None,
            session.status if session else None,
        ).model_dump(),
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
        # Only advertise the container when it is actually reachable — a locked
        # challenge shows nothing about how it is played.
        has_container=(not locked and challenge.container_template_id is not None),
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
    await achievement_service.evaluate(db, current.user.id, achievement_service.HINT, redis=redis)

    if result.cost_charged:
        background.add_task(scoreboard_cache.mark_dirty, redis)

    return UnlockHintResponse(
        body=result.body,
        cost_charged=result.cost_charged,
        already_unlocked=result.already_unlocked,
        new_total=await scoring.user_score(db, current.user.id),
    )


def _puzzle_response(view: puzzle_play.PuzzleView) -> PuzzleStateResponse:
    return PuzzleStateResponse(
        kind=view.kind,
        puzzle=view.puzzle,
        status=view.status,
        moves_used=view.moves_used,
        solved=view.solved,
        feedback=view.feedback,
        xp_awarded=view.xp_awarded,
    )


@router.get("/challenges/{challenge_id}/puzzle")
async def get_puzzle(challenge_id: UUID, db: DbSession, current: Player) -> PuzzleStateResponse:
    """Today's puzzle as it stands for this player.

    Starts nothing. Opening a puzzle to look at it does not commit you to
    playing it — the session, and the clock on the guesses, begin with the first
    move.
    """
    return _puzzle_response(await puzzle_play.view_for_player(db, challenge_id, current.user.id))


@router.post("/challenges/{challenge_id}/puzzle/move")
async def play_puzzle(
    challenge_id: UUID,
    payload: PuzzleMoveRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    current: Player,
) -> PuzzleStateResponse:
    """One move: a guess, a group, a check.

    A single endpoint for all three games — visibility, rate limiting, the lock,
    the prerequisites and whether the session is already over are the same five
    questions whichever game it is, and only then does the kind matter.
    """
    view = await puzzle_play.apply_move(
        db,
        redis,
        current.user,
        challenge_id,
        payload.move,
        ip=request.client.host if request.client else None,
        request_id=_request_id(request),
    )

    if view.xp_awarded:
        # A solve moves this player and, through decay, everyone else who has
        # solved it. Queued so the recompute cannot see this transaction before
        # it commits — the same reason as the flag path.
        background.add_task(scoreboard_cache.mark_dirty, redis)

    return _puzzle_response(view)


@router.post("/challenges/{challenge_id}/puzzle/save")
async def save_puzzle(
    challenge_id: UUID,
    payload: PuzzleSaveRequest,
    db: DbSession,
    redis: RedisClient,
    current: Player,
) -> PuzzleStateResponse:
    """Keep what has been typed so far. Crossword only.

    A flush, not an autosave: the client calls it on leaving, and every check
    carries the grid anyway. It evaluates nothing, so it can never solve, fail or
    score anything.
    """
    return _puzzle_response(
        await puzzle_play.save_progress(db, redis, current.user, challenge_id, payload.model_dump())
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
        message = f"Correct. {outcome.points_awarded} XP."
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

    # Images are served inline so an <img> in a challenge body renders reliably
    # and a player can open the picture in its own tab (spec 063 §5). Everything
    # else stays an attachment, and the Files list keeps its `download`
    # attribute, which forces a save either way.
    disposition = "inline" if artifact.content_type.startswith("image/") else "attachment"

    return StreamingResponse(
        artifact_service.stream_artifact(settings, artifact),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{artifact.filename}"',
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
