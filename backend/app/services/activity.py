"""Recent public events, for the ticker (spec 069).

An event where 200 people are playing at once currently looks, from any one
screen, like an event where nobody is. This puts the room back on the page.

**It names the zone, not the challenge.** That is the spec's §3 decision, and it
is enforced here rather than in the client: a title the client is asked to hide
is a title in the payload, and somebody will read it. Naming the challenge would
hand every watcher a list of solvable work.

Boss kills are the exception and are named in full — spec 032 already broadcasts
the first kill of each boss to everybody by name, and being first is the entire
point of them.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import BOSS_TIER_LEVEL, Category, Challenge
from app.models.play import Solve
from app.models.user import User, UserRole, UserStatus

#: Enough to fill the ticker with room to spare, and small enough that the
#: whole thing rides the board's existing recompute for nothing.
LIMIT = 20


@dataclass(frozen=True)
class ActivityItem:
    kind: str
    display_name: str
    zone_name: str
    #: Null unless `kind` is "boss". §3, enforced on the server.
    challenge_title: str | None
    tier: str | None
    tier_level: int | None
    at: datetime


async def recent(db: AsyncSession, limit: int = LIMIT) -> list[ActivityItem]:
    rows = (
        await db.execute(
            select(
                User.display_name,
                Category.name,
                Challenge.title,
                Challenge.boss_tier,
                Solve.submitted_at,
            )
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .join(User, User.id == Solve.user_id)
            .where(
                # Staff accounts exist to run the event, not to win it — the
                # same exclusion the board makes.
                User.role == UserRole.PLAYER,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(Solve.submitted_at.desc())
            .limit(limit)
        )
    ).all()

    items = []
    for display_name, zone_name, title, tier, at in rows:
        is_boss = tier is not None
        items.append(
            ActivityItem(
                kind="boss" if is_boss else "solve",
                display_name=display_name,
                zone_name=zone_name,
                # The line that matters: a non-boss row carries no title.
                challenge_title=title if is_boss else None,
                tier=tier.value if is_boss else None,
                tier_level=BOSS_TIER_LEVEL[tier] if is_boss else None,
                at=at,
            )
        )
    return items
