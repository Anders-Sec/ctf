"""Response models for the dungeon map (spec 019)."""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.challenges import UnlockRequirementResponse


class ZoneResponse(BaseModel):
    id: UUID
    name: str
    #: Matches the artwork filename, which is how a tile is wired to its zone.
    slug: str
    ability: str
    display_order: int
    #: Top-left corner in map pixels — authored if placed, derived otherwise.
    x: int
    y: int
    locked: bool
    unlock_requirements: list[UnlockRequirementResponse] = []
    cleared: int
    total: int


class EdgeResponse(BaseModel):
    """A corridor: `from_zone_id` is what opens `to_zone_id`."""

    from_zone_id: UUID
    to_zone_id: UUID


class MapResponse(BaseModel):
    #: Dim locked zones. Presentation only — the same zones are returned either
    #: way, so fog adds no leak surface.
    fog_of_war: bool
    zones: list[ZoneResponse]
    edges: list[EdgeResponse]


class SetMapPositionRequest(BaseModel):
    """Both null returns the zone to its derived position."""

    x: int | None = None
    y: int | None = None


class MapPositionResponse(BaseModel):
    x: int | None
    y: int | None


class GateResponse(BaseModel):
    """One gate on a zone, as an admin edits it (spec 022)."""

    id: UUID
    requirement_type: str
    description: str
    required_category_id: UUID | None
    required_category_name: str | None
    required_skill_id: UUID | None
    required_skill_name: str | None
    threshold: int | None
    #: Advisory: a percentage gate on an empty zone can never be met.
    source_has_no_challenges: bool


class GraphZoneResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    #: False means no path from a zone that is open at the start.
    reachable: bool
    published_challenges: int
    gates: list[GateResponse]


class MapGraphResponse(BaseModel):
    zones: list[GraphZoneResponse]
