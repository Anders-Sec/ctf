"""Score overrides, broken-challenge triage, and the operations dashboard.

Reads are open to organizers so event staff can watch without being able to
change anything; every write requires admin.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession, Player, RedisClient, Staff
from app.models.audit import AuditLog
from app.models.challenge import Challenge
from app.models.play import ScoreAdjustment
from app.models.report import ChallengeReport, ReportStatus
from app.models.team import Team
from app.models.user import User
from app.schemas.admin_ops import (
    AdjustmentResponse,
    AuditEntryResponse,
    BulkReleaseRequest,
    ChallengeHealthResponse,
    CreateAdjustmentRequest,
    ReportRequest,
    ReportResponse,
    ReverseAdjustmentRequest,
    TriageReportRequest,
)
from app.schemas.auth import MessageResponse
from app.services import admin_ops
from app.services.scoreboard_cache import mark_dirty

router = APIRouter(tags=["admin-ops"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _name_lookup(db: DbSession, adjustments: list[ScoreAdjustment]) -> tuple[dict, dict]:
    """Resolve subject and actor names so the UI is not full of raw uuids."""
    user_ids = {a.user_id for a in adjustments if a.user_id} | {
        a.created_by_user_id for a in adjustments if a.created_by_user_id
    }
    team_ids = {a.team_id for a in adjustments if a.team_id}

    users = (
        dict(
            (
                await db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))
            ).all()
        )
        if user_ids
        else {}
    )
    teams = (
        dict((await db.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids)))).all())
        if team_ids
        else {}
    )
    return users, teams


@router.post("/admin/adjustments", status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: CreateAdjustmentRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> AdjustmentResponse:
    adjustment = await admin_ops.create_adjustment(
        db,
        current.user,
        points=payload.points,
        reason=payload.reason,
        user_id=payload.user_id,
        team_id=payload.team_id,
        request_id=_request_id(request),
    )
    # An override moves a board just as a solve does. Queued so the recompute
    # cannot read this transaction before it commits.
    background.add_task(mark_dirty, redis)
    users, teams = await _name_lookup(db, [adjustment])
    return _adjustment_response(adjustment, users, teams, None)


def _adjustment_response(
    adjustment: ScoreAdjustment, users: dict, teams: dict, reversed_by_id: UUID | None
) -> AdjustmentResponse:
    return AdjustmentResponse(
        id=adjustment.id,
        user_id=adjustment.user_id,
        team_id=adjustment.team_id,
        subject_name=(
            users.get(adjustment.user_id) if adjustment.user_id else teams.get(adjustment.team_id)
        ),
        points=adjustment.points,
        reason=adjustment.reason,
        created_by_user_id=adjustment.created_by_user_id,
        created_by_name=users.get(adjustment.created_by_user_id),
        reverses_id=adjustment.reverses_id,
        reversed_by_id=reversed_by_id,
        created_at=adjustment.created_at,
    )


@router.get("/admin/adjustments")
async def list_adjustments(
    db: DbSession,
    current: Staff,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AdjustmentResponse]:
    rows = (
        (
            await db.execute(
                select(ScoreAdjustment)
                .order_by(ScoreAdjustment.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    users, teams = await _name_lookup(db, list(rows))

    # A reversed entry is shown struck through, never hidden — the record of the
    # original decision is the point.
    reversed_by = {row.reverses_id: row.id for row in rows if row.reverses_id is not None}
    return [_adjustment_response(row, users, teams, reversed_by.get(row.id)) for row in rows]


@router.post("/admin/adjustments/{adjustment_id}/reverse")
async def reverse_adjustment(
    adjustment_id: UUID,
    payload: ReverseAdjustmentRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> AdjustmentResponse:
    reversal = await admin_ops.reverse_adjustment(
        db, current.user, adjustment_id, payload.reason, request_id=_request_id(request)
    )
    background.add_task(mark_dirty, redis)
    users, teams = await _name_lookup(db, [reversal])
    return _adjustment_response(reversal, users, teams, None)


# --------------------------------------------------------------------------
# Broken-challenge reports
# --------------------------------------------------------------------------


@router.post("/challenges/{challenge_id}/report", status_code=status.HTTP_201_CREATED)
async def report_challenge(
    challenge_id: UUID,
    payload: ReportRequest,
    db: DbSession,
    current: Player,
) -> ReportResponse:
    """A player says a challenge is broken. Idempotent while one is open."""
    report = await admin_ops.report_challenge(db, current.user, challenge_id, payload.message)
    return ReportResponse(
        id=report.id,
        challenge_id=report.challenge_id,
        challenge_title=None,
        user_id=report.user_id,
        reporter_name=current.user.display_name,
        message=report.message,
        status=report.status,
        resolution_note=report.resolution_note,
        created_at=report.created_at,
    )


@router.get("/admin/reports")
async def list_reports(
    db: DbSession,
    current: Staff,
    report_status: ReportStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ReportResponse]:
    conditions = [] if report_status is None else [ChallengeReport.status == report_status]
    rows = (
        (
            await db.execute(
                select(ChallengeReport)
                .where(*conditions)
                .order_by(ChallengeReport.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    titles = (
        dict(
            (
                await db.execute(
                    select(Challenge.id, Challenge.title).where(
                        Challenge.id.in_({row.challenge_id for row in rows})
                    )
                )
            ).all()
        )
        if rows
        else {}
    )
    names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.display_name).where(
                        User.id.in_({row.user_id for row in rows})
                    )
                )
            ).all()
        )
        if rows
        else {}
    )

    return [
        ReportResponse(
            id=row.id,
            challenge_id=row.challenge_id,
            challenge_title=titles.get(row.challenge_id),
            user_id=row.user_id,
            reporter_name=names.get(row.user_id),
            message=row.message,
            status=row.status,
            resolution_note=row.resolution_note,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/admin/reports/{report_id}/status")
async def triage_report(
    report_id: UUID,
    payload: TriageReportRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    await admin_ops.set_report_status(
        db,
        current.user,
        report_id,
        payload.status,
        payload.note,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Report updated.")


# --------------------------------------------------------------------------
# Dashboard, health and scheduling
# --------------------------------------------------------------------------


@router.get("/admin/dashboard")
async def dashboard(db: DbSession, current: Staff) -> dict:
    return await admin_ops.dashboard(db)


@router.get("/admin/challenge-health")
async def challenge_health(db: DbSession, current: Staff) -> list[ChallengeHealthResponse]:
    return [ChallengeHealthResponse(**row.__dict__) for row in await admin_ops.challenge_health(db)]


@router.post("/admin/challenges/release")
async def bulk_release(
    payload: BulkReleaseRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    count = await admin_ops.bulk_release(
        db,
        current.user,
        payload.challenge_ids,
        payload.release_at,
        payload.pre_release_state,
        request_id=_request_id(request),
    )
    return MessageResponse(message=f"{count} challenges scheduled.")


@router.get("/admin/audit-log")
async def read_audit(
    db: DbSession,
    current: Staff,
    action: str | None = None,
    actor_user_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEntryResponse]:
    """The audit log with names resolved, rather than a wall of uuids."""
    conditions = []
    if action:
        conditions.append(AuditLog.action.startswith(action))
    if actor_user_id:
        conditions.append(AuditLog.actor_user_id == actor_user_id)

    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.display_name).where(
                        User.id.in_({row.actor_user_id for row in rows if row.actor_user_id})
                    )
                )
            ).all()
        )
        if rows
        else {}
    )

    return [
        AuditEntryResponse(
            id=row.id,
            action=row.action,
            actor_user_id=row.actor_user_id,
            actor_name=names.get(row.actor_user_id),
            target_type=row.target_type,
            target_id=row.target_id,
            reason=row.reason,
            metadata=row.meta,
            request_id=row.request_id,
            created_at=row.created_at,
        )
        for row in rows
    ]
