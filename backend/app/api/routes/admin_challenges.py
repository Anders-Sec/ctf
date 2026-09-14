"""Admin CRUD for challenges, answer rules, categories and artifacts.

Reads are open to organizers so staff can check a challenge without being able
to rewrite it; every write requires admin. The full editor is spec 006's job —
this is the minimum without which an event cannot be set up at all.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Admin, AppSettings, DbSession, Staff
from app.errors import ConflictError, NotFoundError
from app.models.challenge import (
    MINIMUM_POINTS_FRACTION,
    BossTier,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    Difficulty,
    ScoringMode,
    points_for,
)
from app.models.play import Solve, Submission
from app.schemas.admin_challenges import (
    AddPrerequisiteRequest,
    AdminAnswerResponse,
    AdminChallengeDetail,
    AdminChallengeSummary,
    AnswerTestRequest,
    AnswerTestResponse,
    BulkItemResult,
    BulkRequest,
    BulkResultResponse,
    CreateAnswerRequest,
    CreateCategoryRequest,
    CreateChallengeRequest,
    DeletePreviewResponse,
    EmptiedZoneResponse,
    PrerequisiteResponse,
    SetStateRequest,
    SubmissionLogEntry,
    UpdateChallengeRequest,
    ZoneSummaryResponse,
)
from app.schemas.auth import MessageResponse
from app.schemas.challenges import ArtifactResponse, CategoryResponse
from app.services import answers as answer_service
from app.services import artifacts as artifact_service
from app.services import challenge_bulk, challenge_manager, scoring
from app.services import challenges as challenge_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["admin-challenges"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _load(db: DbSession, challenge_id: UUID) -> Challenge:
    challenge = (
        await db.execute(
            select(Challenge)
            .options(
                selectinload(Challenge.category),
                selectinload(Challenge.answers),
                selectinload(Challenge.artifacts),
            )
            .where(Challenge.id == challenge_id)
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise NotFoundError("No such challenge.")
    return challenge


def _detail(
    challenge: Challenge,
    solve_count: int,
    value: int,
    prerequisites: list[Challenge] | None = None,
) -> AdminChallengeDetail:
    return AdminChallengeDetail(
        id=challenge.id,
        title=challenge.title,
        slug=challenge.slug,
        category=CategoryResponse.model_validate(challenge.category, from_attributes=True),
        difficulty=challenge.difficulty,
        state=challenge.state,
        release_at=challenge.release_at,
        pre_release_state=challenge.pre_release_state,
        initial_points=challenge.initial_points,
        minimum_points=challenge.minimum_points,
        decay_threshold=challenge.decay_threshold,
        scoring=challenge.scoring,
        decay_basis=challenge.decay_basis,
        max_attempts=challenge.max_attempts,
        solve_count=solve_count,
        current_value=value,
        body=challenge.body,
        # Answer values are returned in full: an admin who cannot see the
        # expected answer cannot debug a challenge nobody is solving.
        answers=[
            AdminAnswerResponse.model_validate(answer, from_attributes=True)
            for answer in challenge.answers
        ],
        artifacts=[
            ArtifactResponse.model_validate(artifact, from_attributes=True)
            for artifact in challenge.artifacts
        ],
        container_template_id=challenge.container_template_id,
        prerequisites=[
            PrerequisiteResponse(challenge_id=p.id, title=p.title) for p in (prerequisites or [])
        ],
        created_at=challenge.created_at,
    )


async def _detail_response(
    db: DbSession, challenge: Challenge, solve_count: int, value: int
) -> AdminChallengeDetail:
    prereqs = await challenge_service.list_prerequisites(db, challenge.id)
    return _detail(challenge, solve_count, value, prereqs)


@router.get("/challenges")
async def list_challenges(
    db: DbSession,
    current: Staff,
    search: str | None = Query(default=None, max_length=200),
    category_id: UUID | None = Query(default=None),
    state: ChallengeState | None = Query(default=None),
    difficulty: Difficulty | None = Query(default=None),
    boss_tier: BossTier | None = Query(default=None),
    is_boss: bool | None = Query(default=None),
    has_container: bool | None = Query(default=None),
    problem: challenge_manager.Problem | None = Query(
        default=None, description="A canned 'what is not finished' query (spec 041)."
    ),
    sort: challenge_manager.Sort = Query(default=challenge_manager.Sort.TITLE),
) -> list[AdminChallengeSummary]:
    """Every challenge, drafts included, filtered server-side (spec 041).

    Server-side because at 242 the useful questions are set-shaped — "everything
    with no flag", "every challenge in a zone with no boss" — and because spec
    042's "select all N matching" needs the server to decide the set.
    """
    challenges, counts = await challenge_manager.list_challenges(
        db,
        challenge_manager.ChallengeFilters(
            search=search,
            category_id=category_id,
            state=state,
            difficulty=difficulty,
            boss_tier=boss_tier,
            is_boss=is_boss,
            has_container=has_container,
            problem=problem,
            sort=sort,
        ),
    )
    solves = await scoring.solve_counts_for(db, [c.id for c in challenges])
    now = datetime.now(UTC)

    summaries = [
        AdminChallengeSummary(
            id=c.id,
            title=c.title,
            slug=c.slug,
            category=CategoryResponse.model_validate(c.category, from_attributes=True),
            difficulty=c.difficulty,
            state=c.state,
            effective_state=c.effective_state(now),
            release_at=c.release_at,
            solve_count=solves.get(c.id, 0),
            current_value=scoring.challenge_value(c, solves.get(c.id, 0)),
            initial_points=c.initial_points,
            boss_tier=c.boss_tier,
            ai_ladder_level=c.ai_ladder_level,
            has_container=c.container_template_id is not None,
            answer_count=counts.answers.get(c.id, 0),
            hint_count=counts.hints.get(c.id, 0),
            skill_count=counts.skills.get(c.id, 0),
            prerequisite_count=counts.prerequisites.get(c.id, 0),
        )
        for c in challenges
    ]
    if sort is challenge_manager.Sort.SOLVES:
        # Counted outside the query, so ordered outside it too.
        summaries.sort(key=lambda s: (-s.solve_count, s.title))
    return summaries


@router.get("/zones")
async def list_zones(db: DbSession, current: Staff) -> list[ZoneSummaryResponse]:
    """What each zone's header row shows: how much of it exists, what it is
    worth against the 1,900 budget, and whether it has a boss (spec 041)."""
    return [
        ZoneSummaryResponse(**vars(zone)) for zone in await challenge_manager.zone_summaries(db)
    ]


@router.post("/challenges/bulk/preview-delete")
async def preview_bulk_delete(
    payload: BulkRequest, db: DbSession, current: Admin
) -> DeletePreviewResponse:
    """What a bulk delete would actually do, for the confirm dialog.

    Two things the selection cannot show on its own: which rows are undeletable
    because people have solved them, and which zones would disappear along with
    their last challenge.
    """
    preview = await challenge_bulk.preview_delete(db, payload.challenge_ids)
    return DeletePreviewResponse(
        deletable=preview.deletable,
        blocked=[BulkItemResult(**vars(item)) for item in preview.blocked],
        zones_emptied=[EmptiedZoneResponse(**vars(zone)) for zone in preview.zones_emptied],
    )


@router.post("/challenges/bulk")
async def bulk_edit(
    payload: BulkRequest, request: Request, db: DbSession, current: Admin
) -> BulkResultResponse:
    """Apply one edit to many challenges (spec 042).

    Per-item results rather than all-or-nothing: a challenge with solves cannot
    be deleted, and refusing the other nine because of it would be obstructive.
    """
    challenge_bulk.validate_value(payload.action, payload.value)
    result = await challenge_bulk.apply(db, payload.action, payload.challenge_ids, payload.value)

    # One entry, not one per challenge. A bulk edit is a single decision, and 242
    # audit rows for it would bury everything else in the log.
    await record_audit(
        db,
        action=f"challenge.bulk.{payload.action.value}",
        target_type="challenge",
        target_id=None,
        actor_user_id=current.user.id,
        meta={
            "requested": len(payload.challenge_ids),
            "succeeded": result.succeeded,
            "failed": result.failed,
            "value": payload.value,
            "categories_deleted": result.categories_deleted,
            "challenge_ids": [str(cid) for cid in payload.challenge_ids],
        },
        request_id=_request_id(request),
    )

    return BulkResultResponse(
        succeeded=result.succeeded,
        failed=result.failed,
        results=[BulkItemResult(**vars(item)) for item in result.results],
        categories_deleted=result.categories_deleted,
    )


@router.post("/challenges", status_code=status.HTTP_201_CREATED)
async def create_challenge(
    payload: CreateChallengeRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Admin,
) -> AdminChallengeDetail:
    if await db.scalar(select(Challenge.id).where(Challenge.slug == payload.slug)):
        raise ConflictError("That slug is already taken.", code="slug_taken")

    _validate_threshold(payload.decay_threshold)

    data = payload.model_dump()
    category = await challenge_service.resolve_or_create_category(db, data.pop("category"))

    # XP is the admin's number, not a derivation (spec 040). Difficulty only
    # *suggests* it, for an admin who did not type one — and never touches it
    # again afterwards, so relabelling a challenge cannot silently change what
    # it pays.
    xp_base = settings.xp_base
    difficulty = data["difficulty"]
    if data.get("initial_points") is None:
        data["initial_points"] = points_for(difficulty, xp_base)
    if data.get("minimum_points") is None:
        data["minimum_points"] = _default_minimum(data["initial_points"])
    if data.get("scoring") is None:
        data["scoring"] = ScoringMode.STATIC
    _validate_xp_range(data["initial_points"], data["minimum_points"])

    challenge = Challenge(
        **data,
        category_id=category.id,
        author_user_id=current.user.id,
    )
    db.add(challenge)
    await db.flush()

    await record_audit(
        db,
        action="challenge.create",
        target_type="challenge",
        target_id=challenge.id,
        actor_user_id=current.user.id,
        meta={"slug": challenge.slug},
        request_id=_request_id(request),
    )
    return await _detail_response(
        db, await _load(db, challenge.id), 0, scoring.challenge_value(challenge, 0)
    )


def _default_minimum(xp: int) -> int:
    """The floor decay stops at, when the admin did not name one."""
    return max(1, int(xp * MINIMUM_POINTS_FRACTION))


def _validate_threshold(threshold: int) -> None:
    # The curve divides by the threshold.
    if threshold < 2:
        raise ConflictError(
            "The decay threshold must be at least 2.", code="invalid_decay_threshold"
        )


def _validate_xp_range(xp: int, minimum: int) -> None:
    """Both ends are typed now (spec 040), so the range can be inverted — and a
    floor above the ceiling makes the decay curve run backwards."""
    if minimum > xp:
        raise ConflictError(
            f"Minimum XP ({minimum}) cannot be above the challenge's XP ({xp}).",
            code="invalid_xp_range",
        )


@router.get("/challenges/{challenge_id}")
async def get_challenge(challenge_id: UUID, db: DbSession, current: Staff) -> AdminChallengeDetail:
    challenge = await _load(db, challenge_id)
    count = await scoring.solve_count(db, challenge)
    return await _detail_response(db, challenge, count, scoring.challenge_value(challenge, count))


async def _check_zone_has_no_other_boss(db: DbSession, challenge, changes: dict) -> None:
    """One boss per zone (spec 031).

    The database enforces it with a partial unique index; this exists so the
    error names the challenge already holding the slot instead of surfacing a
    constraint violation.
    """
    category_id = changes.get("category_id", challenge.category_id)
    incumbent = (
        await db.execute(
            select(Challenge).where(
                Challenge.category_id == category_id,
                Challenge.boss_tier.is_not(None),
                Challenge.id != challenge.id,
            )
        )
    ).scalar_one_or_none()
    if incumbent is not None:
        raise ConflictError(
            f"{incumbent.title!r} is already the boss of this zone. Clear its tier first.",
            code="zone_has_boss",
        )


async def _check_ladder_rung_is_free(db: DbSession, challenge: Challenge, level: int) -> None:
    """One challenge per rung of the System AI ladder (spec 033).

    The database enforces it with a partial unique index; this exists so the
    error names the challenge already holding the rung. It matters more than the
    boss equivalent: the engine resolves a level's flag *through* this column, so
    two challenges claiming rung 3 would make the prompt it builds ambiguous.
    """
    incumbent = (
        await db.execute(
            select(Challenge).where(
                Challenge.ai_ladder_level == level,
                Challenge.id != challenge.id,
            )
        )
    ).scalar_one_or_none()
    if incumbent is not None:
        raise ConflictError(
            f"{incumbent.title!r} is already level {level} of the System AI ladder. "
            "Clear its level first.",
            code="ladder_rung_taken",
        )


@router.patch("/challenges/{challenge_id}")
async def update_challenge(
    challenge_id: UUID,
    payload: UpdateChallengeRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Admin,
) -> AdminChallengeDetail:
    challenge = await _load(db, challenge_id)
    changes = payload.model_dump(exclude_unset=True)

    _validate_threshold(changes.get("decay_threshold", challenge.decay_threshold))

    # A difficulty change no longer moves the value (spec 040): difficulty is a
    # label, and an admin relabelling something mid-event must not silently
    # change what it pays. XP moves only when this request says so.
    if "minimum_points" in changes and changes["minimum_points"] is None:
        changes["minimum_points"] = _default_minimum(
            changes.get("initial_points", challenge.initial_points)
        )
    # An explicit null means "use the default", not "store null".
    for field in ("scoring", "initial_points"):
        if field in changes and changes[field] is None:
            changes.pop(field)
    _validate_xp_range(
        changes.get("initial_points", challenge.initial_points),
        changes.get("minimum_points", challenge.minimum_points),
    )

    if changes.get("boss_tier") is not None:
        await _check_zone_has_no_other_boss(db, challenge, changes)

    if changes.get("ai_ladder_level") is not None:
        await _check_ladder_rung_is_free(db, challenge, changes["ai_ladder_level"])

    renaming = "slug" in changes and changes["slug"] != challenge.slug
    if renaming and await db.scalar(select(Challenge.id).where(Challenge.slug == changes["slug"])):
        raise ConflictError("That slug is already taken.", code="slug_taken")

    # A container template must exist (or be explicitly detached with null).
    if changes.get("container_template_id") is not None:
        from app.models.instance import ContainerTemplate

        if await db.get(ContainerTemplate, changes["container_template_id"]) is None:
            raise NotFoundError("No such container template.")

    # Category is a name, resolved to (or creating) a row. A zone the move leaves
    # empty is left alone (spec 043) — empty is what a zone looks like before its
    # challenges are written.
    new_category_name = changes.pop("category", None)

    for field, value in changes.items():
        setattr(challenge, field, value)
    if new_category_name is not None:
        category = await challenge_service.resolve_or_create_category(db, new_category_name)
        # Assign the relationship, not just the FK, so the reloaded detail sees
        # the new category rather than the stale one.
        challenge.category = category
        changes["category"] = category.name
    await db.flush()

    await record_audit(
        db,
        action="challenge.update",
        target_type="challenge",
        target_id=challenge.id,
        actor_user_id=current.user.id,
        meta={key: str(value) for key, value in changes.items()},
        request_id=_request_id(request),
    )
    count = await scoring.solve_count(db, challenge)
    return await _detail_response(
        db, await _load(db, challenge.id), count, scoring.challenge_value(challenge, count)
    )


@router.post("/challenges/{challenge_id}/state")
async def set_state(
    challenge_id: UUID,
    payload: SetStateRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminChallengeDetail:
    """Publish, lock or hide a challenge immediately.

    Hiding a challenge stops new attempts. It does not touch existing solves —
    history is not rewritten because a challenge turned out to be broken. Use a
    score adjustment for that, with a reason.
    """
    challenge = await _load(db, challenge_id)
    previous = challenge.state
    challenge.state = payload.state
    await db.flush()

    await record_audit(
        db,
        action="challenge.set_state",
        target_type="challenge",
        target_id=challenge.id,
        actor_user_id=current.user.id,
        reason=payload.reason,
        meta={"from": previous.value, "to": payload.state.value},
        request_id=_request_id(request),
    )
    count = await scoring.solve_count(db, challenge)
    return await _detail_response(db, challenge, count, scoring.challenge_value(challenge, count))


@router.delete("/challenges/{challenge_id}")
async def delete_challenge(
    challenge_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    challenge = await _load(db, challenge_id)

    solves = await db.scalar(
        select(func.count()).select_from(Solve).where(Solve.challenge_id == challenge_id)
    )
    if solves:
        # Deleting would erase the solves that scored for people. Hiding is the
        # operation an admin actually wants here.
        raise ConflictError(
            f"{solves} players have solved this. Hide it instead of deleting it.",
            code="challenge_has_solves",
        )

    slug = challenge.slug
    await db.delete(challenge)
    await db.flush()
    # The zone stays (spec 043). It used to be pruned when its last challenge
    # went, which quietly destroyed a seeded zone's ability mapping, display
    # order and map position, and detached its skills.

    await record_audit(
        db,
        action="challenge.delete",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"slug": slug},
        request_id=_request_id(request),
    )
    await db.flush()
    return MessageResponse(message="Challenge deleted.")


# --------------------------------------------------------------------------
# Answer rules
# --------------------------------------------------------------------------


@router.post("/challenges/{challenge_id}/answers", status_code=status.HTTP_201_CREATED)
async def add_answer(
    challenge_id: UUID,
    payload: CreateAnswerRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminAnswerResponse:
    challenge = await _load(db, challenge_id)
    # Validated here so a broken pattern fails in the editor rather than
    # silently rejecting every correct answer at 09:00 on event day.
    answer_service.validate_rule(payload.match_type, payload.value, payload.options)

    answer = ChallengeAnswer(
        challenge_id=challenge.id,
        match_type=payload.match_type,
        value=payload.value,
        options=payload.options,
        label=payload.label,
        display_order=payload.display_order,
    )
    db.add(answer)
    await db.flush()

    await record_audit(
        db,
        action="challenge.answer_add",
        target_type="challenge",
        target_id=challenge.id,
        actor_user_id=current.user.id,
        # The value is deliberately not logged: the audit log is read by
        # organizers, and it is not the place to broadcast answers.
        meta={"match_type": payload.match_type.value, "label": payload.label or ""},
        request_id=_request_id(request),
    )
    return AdminAnswerResponse.model_validate(answer, from_attributes=True)


@router.delete("/challenges/{challenge_id}/answers/{answer_id}")
async def delete_answer(
    challenge_id: UUID,
    answer_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    answer = (
        await db.execute(
            select(ChallengeAnswer).where(
                ChallengeAnswer.id == answer_id, ChallengeAnswer.challenge_id == challenge_id
            )
        )
    ).scalar_one_or_none()
    if answer is None:
        raise NotFoundError("No such answer rule.")

    await db.delete(answer)
    await record_audit(
        db,
        action="challenge.answer_delete",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"match_type": answer.match_type.value},
        request_id=_request_id(request),
    )
    await db.flush()
    return MessageResponse(message="Answer rule removed.")


@router.post("/challenges/{challenge_id}/answers/test")
async def test_answer(
    challenge_id: UUID,
    payload: AnswerTestRequest,
    db: DbSession,
    current: Admin,
) -> AnswerTestResponse:
    """Dry-run a candidate answer against the rules.

    Records nothing. Authoring a regex blind and finding out during the event is
    how challenges break, so this exists before the first player ever sees one.
    """
    challenge = await _load(db, challenge_id)
    verdict = answer_service.check(payload.candidate, challenge.answers)

    return AnswerTestResponse(
        correct=verdict.correct,
        matched_answer_id=verdict.matched_answer.id if verdict.matched_answer else None,
        matched_label=verdict.matched_answer.label if verdict.matched_answer else None,
        errors=list(verdict.errors),
    )


# --------------------------------------------------------------------------
# Prerequisites (spec 014)
# --------------------------------------------------------------------------


@router.post("/challenges/{challenge_id}/prerequisites", status_code=status.HTTP_201_CREATED)
async def add_prerequisite(
    challenge_id: UUID,
    payload: AddPrerequisiteRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> list[PrerequisiteResponse]:
    await _load(db, challenge_id)
    await challenge_service.add_prerequisite(db, challenge_id, payload.required_challenge_id)
    await record_audit(
        db,
        action="challenge.prerequisite_add",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"required": str(payload.required_challenge_id)},
        request_id=_request_id(request),
    )
    prereqs = await challenge_service.list_prerequisites(db, challenge_id)
    return [PrerequisiteResponse(challenge_id=p.id, title=p.title) for p in prereqs]


@router.delete(
    "/challenges/{challenge_id}/prerequisites/{required_challenge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_prerequisite(
    challenge_id: UUID,
    required_challenge_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> None:
    await _load(db, challenge_id)
    await challenge_service.remove_prerequisite(db, challenge_id, required_challenge_id)
    await record_audit(
        db,
        action="challenge.prerequisite_remove",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"required": str(required_challenge_id)},
        request_id=_request_id(request),
    )


# --------------------------------------------------------------------------
# Categories and artifacts
# --------------------------------------------------------------------------


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CreateCategoryRequest, db: DbSession, current: Admin
) -> CategoryResponse:
    if await db.scalar(select(Category.id).where(Category.slug == payload.slug)):
        raise ConflictError("That category already exists.", code="category_exists")

    category = Category(**payload.model_dump())
    db.add(category)
    await db.flush()
    return CategoryResponse.model_validate(category, from_attributes=True)


@router.post("/challenges/{challenge_id}/artifacts", status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    challenge_id: UUID,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    current: Admin,
    file: UploadFile = File(...),
    display_order: int = Form(default=0),
) -> ArtifactResponse:
    await _load(db, challenge_id)
    data = await file.read()

    artifact = await artifact_service.store_artifact(
        db,
        settings,
        challenge_id,
        file.filename or "artifact",
        file.content_type,
        data,
    )
    artifact.display_order = display_order
    await db.flush()

    await record_audit(
        db,
        action="challenge.artifact_upload",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"filename": artifact.filename, "size_bytes": artifact.size_bytes},
        request_id=_request_id(request),
    )
    return ArtifactResponse.model_validate(artifact, from_attributes=True)


@router.delete("/challenges/{challenge_id}/artifacts/{artifact_id}")
async def delete_artifact(
    challenge_id: UUID,
    artifact_id: UUID,
    db: DbSession,
    settings: AppSettings,
    current: Admin,
) -> MessageResponse:
    artifact = await artifact_service.get_artifact(db, challenge_id, artifact_id)
    await artifact_service.delete_artifact(db, settings, artifact)
    return MessageResponse(message="File removed.")


@router.get("/submissions")
async def list_submissions(
    db: DbSession,
    current: Staff,
    challenge_id: UUID | None = None,
    user_id: UUID | None = None,
    correct: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[SubmissionLogEntry]:
    """The attempt log. Spec 007 builds detection on top of this."""
    conditions = []
    if challenge_id is not None:
        conditions.append(Submission.challenge_id == challenge_id)
    if user_id is not None:
        conditions.append(Submission.user_id == user_id)
    if correct is not None:
        conditions.append(Submission.is_correct == correct)

    rows = (
        (
            await db.execute(
                select(Submission)
                .where(*conditions)
                .order_by(Submission.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [SubmissionLogEntry.model_validate(row, from_attributes=True) for row in rows]
