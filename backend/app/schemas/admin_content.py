"""Bulk operations on content (spec 058 §4)."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BulkRequest(BaseModel):
    #: Capped at the largest roster plus room: 242 challenges is the biggest
    #: thing here, and "select all" has to be one call rather than several.
    ids: list[UUID] = Field(min_length=1, max_length=500)
    action: str
    #: Meaning depends on the action. Null is legitimate for several of them —
    #: clearing a skill's zone, clearing an achievement's loot box.
    value: Any = None


class BulkResultResponse(BaseModel):
    changed: int
    #: id → why it was refused. A bulk delete that skipped rows has to say which
    #: and why, or it reads as a success that quietly did less than asked.
    refused: dict[str, str]
