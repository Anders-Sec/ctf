"""The dungeon map (spec 017).

A **view** over the challenges a player can already see — never its own set of
rules. It is built on ``challenge_service.list_for_player``, the same call the
list view uses, so the two cannot disagree about what exists and the map cannot
become a second place where visibility is decided (and therefore leaked).

Layout is derived and deterministic: rooms are layered by prerequisite depth
within their zone, ordered by title then id. Every player gets identical
coordinates, and a new challenge lands on the map the moment it is published,
with no admin action. Pinned ``map_x``/``map_y`` override the derived position.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category, ChallengeState, RequirementType, UnlockRequirement
from app.models.event import EventConfig
from app.services import challenges as challenge_service
from app.services import unlocks
from app.services.unlocks import RequirementView


@dataclass(frozen=True)
class Room:
    challenge_id: UUID
    title: str
    zone_id: UUID
    x: int
    y: int
    #: ``cleared`` | ``open`` | ``shut``
    state: str
    value: int
    solved: bool
    unlock_requirements: list[RequirementView]


@dataclass(frozen=True)
class Zone:
    id: UUID
    name: str
    display_order: int
    locked: bool
    unlock_requirements: list[RequirementView]
    cleared: int
    total: int


@dataclass(frozen=True)
class Edge:
    from_challenge_id: UUID
    to_challenge_id: UUID


@dataclass(frozen=True)
class DungeonMap:
    fog_of_war: bool
    zones: list[Zone]
    rooms: list[Room]
    edges: list[Edge]


async def build(db: AsyncSession, user_id: UUID, now: datetime) -> DungeonMap:
    rows = await challenge_service.list_for_player(db, user_id, now)
    visible_ids = {row["challenge"].id for row in rows}

    edges = await _edges(db, visible_ids)
    zones = await _zones(db, user_id, rows, now)
    rooms = _rooms(rows, edges)

    fog = await db.scalar(select(EventConfig.fog_of_war))

    return DungeonMap(
        fog_of_war=bool(fog),
        zones=zones,
        rooms=rooms,
        edges=edges,
    )


async def _edges(db: AsyncSession, visible_ids: set[UUID]) -> list[Edge]:
    """Corridors: prerequisite links where **both** ends are visible.

    Withholding an edge whose other end the player cannot see is what stops a
    corridor from implying a room that is not on their map.
    """
    if not visible_ids:
        return []
    rows = (
        (
            await db.execute(
                select(UnlockRequirement).where(
                    UnlockRequirement.requirement_type == RequirementType.CHALLENGE_SOLVED,
                    UnlockRequirement.challenge_id.in_(visible_ids),
                    UnlockRequirement.required_challenge_id.in_(visible_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        Edge(from_challenge_id=r.required_challenge_id, to_challenge_id=r.challenge_id)
        for r in rows
    ]


async def _zones(db: AsyncSession, user_id: UUID, rows: list[dict], now: datetime) -> list[Zone]:
    category_ids = {row["challenge"].category_id for row in rows}
    if not category_ids:
        return []

    categories = (
        (
            await db.execute(
                select(Category)
                .where(Category.id.in_(category_ids))
                .order_by(Category.display_order, Category.name)
            )
        )
        .scalars()
        .all()
    )

    requirements = (
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.category_id.in_(category_ids))
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

    zones = []
    for category in categories:
        gate = gates.get(category.id)
        zones.append(
            Zone(
                id=category.id,
                name=category.name,
                display_order=category.display_order,
                locked=gate.locked if gate else False,
                unlock_requirements=gate.visible_requirements if gate else [],
                cleared=cleared.get(category.id, 0),
                total=total.get(category.id, 0),
            )
        )
    return zones


def _rooms(rows: list[dict], edges: list[Edge]) -> list[Room]:
    by_zone: dict[UUID, list[dict]] = {}
    for row in rows:
        by_zone.setdefault(row["challenge"].category_id, []).append(row)

    #: gated challenge -> its visible prerequisites, for the depth walk.
    prereqs: dict[UUID, list[UUID]] = {}
    for edge in edges:
        prereqs.setdefault(edge.to_challenge_id, []).append(edge.from_challenge_id)

    rooms: list[Room] = []
    for zone_id, zone_rows in by_zone.items():
        in_zone = {row["challenge"].id for row in zone_rows}
        depths = _depths(in_zone, prereqs)

        # Title then id: Challenge has no display_order, and id is the final
        # tie-break that makes two runs (and two players) agree exactly.
        def sort_key(row: dict, depths: dict[UUID, int] = depths) -> tuple[int, str, str]:
            challenge = row["challenge"]
            return (depths[challenge.id], challenge.title, str(challenge.id))

        ordered = sorted(zone_rows, key=sort_key)

        seen_at_depth: dict[int, int] = {}
        for row in ordered:
            challenge = row["challenge"]
            depth = depths[challenge.id]
            index = seen_at_depth.get(depth, 0)
            seen_at_depth[depth] = index + 1

            rooms.append(
                Room(
                    challenge_id=challenge.id,
                    title=challenge.title,
                    zone_id=zone_id,
                    x=challenge.map_x if challenge.map_x is not None else index,
                    y=challenge.map_y if challenge.map_y is not None else depth,
                    state=_state(row),
                    value=row["value"],
                    solved=row["solved"],
                    unlock_requirements=row.get("unlock_requirements", []),
                )
            )
    return rooms


def _depths(in_zone: set[UUID], prereqs: dict[UUID, list[UUID]]) -> dict[UUID, int]:
    """Depth = one past the deepest *visible* prerequisite inside this zone.

    Only same-zone, visible prerequisites count, so a player who cannot see a
    gating challenge gets no mysterious gap where it would have been. Cycles are
    impossible (014 refuses them); the ``visiting`` guard is belt-and-braces so a
    bad row can never hang a request.
    """
    depths: dict[UUID, int] = {}

    def walk(challenge_id: UUID, visiting: frozenset[UUID]) -> int:
        if challenge_id in depths:
            return depths[challenge_id]
        if challenge_id in visiting:
            return 0
        parents = [p for p in prereqs.get(challenge_id, []) if p in in_zone]
        depth = 0 if not parents else 1 + max(walk(p, visiting | {challenge_id}) for p in parents)
        depths[challenge_id] = depth
        return depth

    for challenge_id in in_zone:
        walk(challenge_id, frozenset())
    return depths


def _state(row: dict) -> str:
    if row["solved"]:
        return "cleared"
    if row["effective_state"] == ChallengeState.LOCKED:
        return "shut"
    return "open"
