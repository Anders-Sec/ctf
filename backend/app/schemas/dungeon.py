"""Response models for the dungeon map (spec 017)."""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.challenges import UnlockRequirementResponse


class RoomResponse(BaseModel):
    challenge_id: UUID
    title: str
    zone_id: UUID
    x: int
    y: int
    #: ``cleared`` | ``open`` | ``shut``
    state: str
    value: int
    solved: bool
    unlock_requirements: list[UnlockRequirementResponse] = []


class ZoneResponse(BaseModel):
    id: UUID
    name: str
    display_order: int
    locked: bool
    unlock_requirements: list[UnlockRequirementResponse] = []
    cleared: int
    total: int


class EdgeResponse(BaseModel):
    from_challenge_id: UUID
    to_challenge_id: UUID


class MapResponse(BaseModel):
    #: Dim locked zones. Presentation only — the same rooms are returned either
    #: way, so fog adds no leak surface.
    fog_of_war: bool
    zones: list[ZoneResponse]
    rooms: list[RoomResponse]
    edges: list[EdgeResponse]


class SetMapPositionRequest(BaseModel):
    """Both null returns the room to its derived position."""

    x: int | None = None
    y: int | None = None


class MapPositionResponse(BaseModel):
    """The room's coordinates after a pin or a clear."""

    x: int | None
    y: int | None
