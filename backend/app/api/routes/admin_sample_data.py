"""Admin sample-data generation, for working on the platform with data in it.

Refused in production: this invents players, solves and scores, and an accidental
click during the real event would be unpleasant to unpick. Everything it creates
is tagged, so the purge takes back exactly what it made.
"""

from fastapi import APIRouter, Request

from app.api.deps import Admin, AppSettings, DbSession
from app.schemas.auth import MessageResponse
from app.schemas.sample_data import SampleDataSummary
from app.services import sample_data as sample_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/sample-data", tags=["admin-sample-data"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("")
async def generate(
    request: Request, db: DbSession, settings: AppSettings, current: Admin
) -> SampleDataSummary:
    """Replace any existing sample data with a fresh set. Safe to press twice."""
    sample_service.ensure_allowed(settings.is_production)

    summary = await sample_service.generate(db)

    await record_audit(
        db,
        action="sample_data.generate",
        target_type="event",
        target_id=None,
        actor_user_id=current.user.id,
        meta={"challenges": summary.challenges, "players": summary.players},
        request_id=_request_id(request),
    )
    return SampleDataSummary(**vars(summary))


@router.delete("")
async def purge(
    request: Request, db: DbSession, settings: AppSettings, current: Admin
) -> MessageResponse:
    sample_service.ensure_allowed(settings.is_production)

    await sample_service.purge(db)

    await record_audit(
        db,
        action="sample_data.purge",
        target_type="event",
        target_id=None,
        actor_user_id=current.user.id,
        meta={},
        request_id=_request_id(request),
    )
    return MessageResponse(message="Sample data removed.")
