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
    #: The tier of this zone's boss, if it has one (spec 031).
    boss_tier: str | None = None


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


class LayoutZone(BaseModel):
    x: int
    y: int


class MapLayoutFile(BaseModel):
    """A portable layout (spec 027).

    Keyed on **slug**, never on category id: categories are seeded with
    ``gen_random_uuid()``, so every environment has different ids for the same
    zones and an id-keyed file would import as nothing at all — silently.
    """

    version: int = 1
    zones: dict[str, LayoutZone]


class LayoutImportResult(BaseModel):
    applied: int
    #: Slugs with no matching category here. Reported, not fatal: environments
    #: drift, and 21 of 22 zones placing is better than none.
    unknown: list[str]
