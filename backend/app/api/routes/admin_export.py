"""Getting the results out (spec 056).

Synchronous and streamed. The largest table is submissions, a few seconds and a
handful of megabytes for this event — a background job with a polling status
endpoint would be more machinery than the data justifies.

Available whenever, not gated on the event having ended: exporting mid-event is
how you check the awards sheet computes what you expect *before* the afternoon
you need it.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import Admin, DbSession, EventCfg, RedisClient, Staff
from app.errors import NotFoundError
from app.services import event_export
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/export", tags=["admin"])

CSV_TYPE = "text/csv; charset=utf-8"

# Route order matters here: `/{name}.csv` is a catch-all and would swallow
# `/submissions-full.csv` if it were declared first, quietly turning the one
# export that needs Admin and an audit entry into a Staff-readable 404.


def _filename(event_name: str | None, stem: str, extension: str) -> str:
    """Named so three downloads in one afternoon do not become "export (2)"."""
    slug = "".join(c if c.isalnum() else "-" for c in (event_name or "event")).strip("-").lower()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return f"{slug or 'event'}-{stem}-{stamp}.{extension}"


def _disposition(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@router.get("/submissions-full.csv")
async def export_submissions_full(
    request: Request,
    db: DbSession,
    redis: RedisClient,
    event: EventCfg,
    current: Admin,
) -> StreamingResponse:
    """Every attempt, verbatim, including addresses.

    In aggregate this file is a list of every flag in the event, because every
    correct submission is one. Its own endpoint, `Admin` only, and taking it is
    written to the audit log — it is legitimate for post-event analysis and it
    is not a file to email around.
    """
    await record_audit(
        db,
        action="export.submissions_full",
        target_type="event",
        target_id=None,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.flush()

    stream = await event_export.submissions_csv(db, full=True)
    return StreamingResponse(
        stream,
        media_type=CSV_TYPE,
        headers=_disposition(_filename(event.name if event else None, "submissions-full", "csv")),
    )


@router.get("/{name}.csv")
async def export_csv(
    name: str,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    event: EventCfg,
    current: Staff,
    full: bool = False,
) -> StreamingResponse:
    if full:
        # The full submissions form is every flag in the event. `Staff` is not
        # enough, and taking it is recorded.
        raise NotFoundError("Use the dedicated endpoint for the full export.")

    try:
        stream = await event_export.build(name, db, redis)
    except KeyError as exc:
        raise NotFoundError(f"No export called {name}.") from exc

    return StreamingResponse(
        stream,
        media_type=CSV_TYPE,
        headers=_disposition(_filename(event.name if event else None, name, "csv")),
    )


@router.get("/archive.zip")
async def export_archive(
    db: DbSession,
    redis: RedisClient,
    event: EventCfg,
    current: Staff,
) -> StreamingResponse:
    """Everything, plus a manifest.

    Excludes the full submissions form, which is only ever downloaded
    deliberately and on its own.
    """
    name = event.name if event else "event"
    payload = await event_export.archive(db, redis, name or "event")

    async def body():
        yield payload

    return StreamingResponse(
        body(),
        media_type="application/zip",
        headers=_disposition(_filename(name, "archive", "zip")),
    )
