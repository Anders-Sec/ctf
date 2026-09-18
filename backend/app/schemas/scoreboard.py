"""Response models for the scoreboard.

Entries stay loosely typed (`dict[str, Any]`) because both boards are computed
once, cached whole, and served from that projection — re-validating every row
through a model on the way out would buy nothing and would mean two places to
change when a column is added.

What *is* enforced is the exclusion: `scoreboard_cache.public_view` strips
`score` before either board is served, and a test asserts no public response
carries it (spec 059 §2).
"""

from typing import Any

from pydantic import BaseModel


class PlayerBoardResponse(BaseModel):
    total: int
    generated_at: str
    entries: list[dict[str, Any]]


class TeamBoardResponse(BaseModel):
    total: int
    generated_at: str
    entries: list[dict[str, Any]]


class MyStandingResponse(BaseModel):
    """A compact header: where you stand, and where your party stands.

    No XP, for §2's reason — this is a board surface, and a party's total sitting
    on an endpoint nobody currently renders is exactly the field that gets
    rendered by accident later. Level is the public shape of the same thing.
    """

    rank: int | None
    level: int
    player_count: int
    team_rank: int | None
    team_level: int | None
    team_count: int


class BossStarResponse(BaseModel):
    """One boss kill, identified by the challenge's slug (spec 059 §3)."""

    slug: str
    tier: str
    #: 1 (Neighborhood) to 6 (Floor), so a client orders without the names.
    level: int
    #: For the hover. Colour carries the tier; this carries which boss.
    title: str


class PartyMemberResponse(BaseModel):
    user_id: str
    display_name: str
    has_avatar: bool
    level: int
    class_name: str | None
    class_rarity: str | None


class PartyPanelResponse(BaseModel):
    """Who a party is (spec 059 §5). Deliberately no XP, member XP included."""

    team_id: str
    name: str
    rank: int
    level: int
    member_count: int
    #: Distinct challenges solved by any current member.
    solve_count: int
    #: Distinct achievements held by current members.
    achievement_count: int
    stars: list[BossStarResponse]
    founded_at: str
    members: list[PartyMemberResponse]


class ActivityItemResponse(BaseModel):
    """One line of the ticker (spec 069).

    `challenge_title` and `tier` are null unless `kind` is "boss" — §3's decision
    enforced on the server, because a title the client is asked to hide is a
    title in the payload.
    """

    kind: str
    display_name: str
    zone_name: str
    challenge_title: str | None
    tier: str | None
    tier_level: int | None
    at: str


class ActivityResponse(BaseModel):
    items: list[ActivityItemResponse]
