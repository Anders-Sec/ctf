"""Import report for the challenge CSV (spec 026)."""

from pydantic import BaseModel


class RowErrorResponse(BaseModel):
    """Row and column, because "invalid difficulty" alone in a 242-row file
    tells an admin nothing about where to look."""

    row: int
    column: str
    problem: str


class ImportReportResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    dry_run: bool
    errors: list[RowErrorResponse]
