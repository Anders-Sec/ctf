"""The dungeon map (spec 017).

A **view** over the challenges a player can already see — never its own set of
rules. It is built on ``challenge_service.list_for_player``, the same call the
list view uses, so the two cannot disagree about what exists and the map cannot
become a second place where visibility is decided (and therefore leaked).

Spec 019 made it a map of **zones**, not of every challenge: 231 rooms is
unreadable and cannot be illustrated, while 22 zones can. Clicking a zone opens
its challenges.

Layout is derived and deterministic — zones are layered by how deep they sit in
the progression graph — so every player sees the same dungeon. Edges are the
progression itself, so a corridor now means "this opens that".
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category, UnlockRequirement
from app.models.event import EventConfig
from app.services import challenges as challenge_service
from app.services import unlocks
from app.services.unlocks import RequirementView

#: Wider than this and a tier wraps onto another row, so the map stays a shape
#: you can take in rather than a strip that scrolls off the side.
MAX_ZONES_PER_ROW = 5

#: Spacing for the *derived* layout, in the same pixel space authored positions
#: use. Coordinates leave this service as pixels either way, so the client never
#: has to know whether a zone was placed by hand or laid out automatically.
TILE = 260
COLUMN_SPACING = TILE + 44
ROW_SPACING = TILE + 34 + 72
MARGIN = 40


@dataclass(frozen=True)
class Zone:
    id: UUID
    name: str
    slug: str
    ability: str
    display_order: int
    #: Top-left corner in map pixels — authored if placed, derived otherwise.
    x: int
    y: int
    locked: bool
    unlock_requirements: list[RequirementView]
    cleared: int
    total: int


@dataclass(frozen=True)
class Edge:
    """A corridor: ``from_zone_id`` is what opens ``to_zone_id``."""

    from_zone_id: UUID
    to_zone_id: UUID


@dataclass(frozen=True)
class DungeonMap:
    fog_of_war: bool
    zones: list[Zone]
    edges: list[Edge]


async def build(db: AsyncSession, user_id: UUID, now: datetime) -> DungeonMap:
    rows = await challenge_service.list_for_player(db, user_id, now)

    categories = (
        (await db.execute(select(Category).order_by(Category.display_order, Category.name)))
        .scalars()
        .all()
    )
    requirements = (
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.category_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    gates = await unlocks.evaluate_groups(db, user_id, list(requirements), now, key="category_id")

    cleared: dict[UUID, int] = {}
    total: dict[UUID, int] = {}
    for row in rows:
        category_id = row["challenge"].category_id
        total[category_id] = total.get(category_id, 0) + 1
        if row["solved"]:
            cleared[category_id] = cleared.get(category_id, 0) + 1

    edges = _edges(categories, list(requirements))
    positions = _layout(categories, edges)

    zones = []
    for category in categories:
        gate = gates.get(category.id)
        # An authored position wins; the derived one is the fallback that keeps a
        # newly added category from vanishing (spec 021).
        derived_x, derived_y = positions[category.id]
        x = category.map_x if category.map_x is not None else derived_x
        y = category.map_y if category.map_y is not None else derived_y
        zones.append(
            Zone(
                id=category.id,
                name=category.name,
                slug=category.slug,
                ability=category.ability.value,
                display_order=category.display_order,
                x=x,
                y=y,
                locked=gate.locked if gate else False,
                unlock_requirements=gate.visible_requirements if gate else [],
                cleared=cleared.get(category.id, 0),
                total=total.get(category.id, 0),
            )
        )

    fog = await db.scalar(select(EventConfig.fog_of_war))
    return DungeonMap(fog_of_war=bool(fog), zones=zones, edges=edges)


def _edges(categories: list[Category], requirements: list[UnlockRequirement]) -> list[Edge]:
    """Corridors are the progression graph: what opens what.

    Only gates that name a source zone become edges — a level gate has no source,
    so it renders as a condition on the zone rather than a corridor from nowhere.
    """
    known = {c.id for c in categories}
    return [
        Edge(from_zone_id=r.required_category_id, to_zone_id=r.category_id)
        for r in requirements
        if r.required_category_id in known and r.category_id in known
    ]


def _layout(categories: list[Category], edges: list[Edge]) -> dict[UUID, tuple[int, int]]:
    """Grid positions, layered by depth in the progression graph.

    Depth is one past the deepest zone that opens it, so the dungeon reads
    outward from Intro. Ordering within a layer is display_order then name then
    id, which makes the result identical for every player and stable between
    reloads.
    """
    parents: dict[UUID, list[UUID]] = {}
    for edge in edges:
        parents.setdefault(edge.to_zone_id, []).append(edge.from_zone_id)

    depths: dict[UUID, int] = {}

    def depth_of(zone_id: UUID, visiting: frozenset[UUID]) -> int:
        if zone_id in depths:
            return depths[zone_id]
        if zone_id in visiting:
            return 0
        sources = parents.get(zone_id, [])
        value = 0 if not sources else 1 + max(depth_of(p, visiting | {zone_id}) for p in sources)
        depths[zone_id] = value
        return value

    for category in categories:
        depth_of(category.id, frozenset())

    ordered = sorted(
        categories,
        key=lambda c: (depths[c.id], c.display_order, c.name, str(c.id)),
    )

    # A tier can be wide — the first wave alone is six zones, and a real event
    # has more — so a tier wraps onto extra rows rather than running off the
    # side of the map. Rows stay grouped by tier, so the dungeon still reads
    # outward from Intro.
    by_depth: dict[int, list] = {}
    for category in ordered:
        by_depth.setdefault(depths[category.id], []).append(category)

    positions: dict[UUID, tuple[int, int]] = {}
    row = 0
    for depth in sorted(by_depth):
        members = by_depth[depth]
        for index, category in enumerate(members):
            column = index % MAX_ZONES_PER_ROW
            line = row + index // MAX_ZONES_PER_ROW
            positions[category.id] = (
                MARGIN + column * COLUMN_SPACING,
                MARGIN + line * ROW_SPACING,
            )
        row += (len(members) - 1) // MAX_ZONES_PER_ROW + 1
    return positions
