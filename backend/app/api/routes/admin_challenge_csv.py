"""Challenge import and export as CSV (spec 026).

The template is the interesting endpoint: it hands back a row for every
challenge an admin is expected to write, with the category and a suggested
difficulty already in place, so planning happens in a spreadsheet rather than in
242 web forms.
"""

from fastapi import APIRouter, File, Query, Request, Response, UploadFile

from app.api.deps import Admin, DbSession, Staff
from app.schemas.challenge_csv import ImportReportResponse, RowErrorResponse
from app.services import challenge_csv
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/challenges", tags=["admin-challenge-csv"])


def _csv(body: str, filename: str) -> Response:
    """text/csv with a filename, so a browser saves rather than renders it."""
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/template.csv")
async def template(db: DbSession, current: Staff) -> Response:
    """A blank plan: every category, eleven rows each, difficulty pre-filled."""
    return _csv(await challenge_csv.build_template(db), "challenge-template.csv")


@router.get("/export.csv")
async def export(db: DbSession, current: Staff) -> Response:
    """Current challenges in the template's shape, so the round-trip is closed."""
    return _csv(await challenge_csv.build_export(db), "challenges.csv")


@router.post("/import")
async def import_challenges(
    request: Request,
    db: DbSession,
    current: Admin,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False, description="Report without writing."),
) -> ImportReportResponse:
    """Validate the whole file, then apply it — or report why it was refused.

    Nothing is written unless every row is good, so a rejected file leaves the
    event exactly as it was.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise challenge_csv.ImportRejected("That file is not UTF-8 text.") from exc

    report = await challenge_csv.import_csv(db, text, dry_run=dry_run)

    if report.ok and not dry_run:
        await record_audit(
            db,
            action="challenge.csv_import",
            target_type="event",
            target_id=None,
            actor_user_id=current.user.id,
            meta={"created": report.created, "updated": report.updated},
            request_id=getattr(request.state, "request_id", None),
        )

    return ImportReportResponse(
        created=report.created,
        updated=report.updated,
        skipped=report.skipped,
        dry_run=report.dry_run,
        errors=[RowErrorResponse(**vars(e)) for e in report.errors],
    )
