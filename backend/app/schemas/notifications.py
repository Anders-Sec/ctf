"""Notification and achievement responses (spec 028)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.notification import NotificationKind


class DismissRequest(BaseModel):
    """What to clear (spec 065 §4).

    Empty means everything. A kind list scopes it, so "clear all" on one inbox
    tab cannot take the other tab's rows with it.
    """

    kinds: list[NotificationKind] = []


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: datetime


class NotificationFeed(BaseModel):
    unread: int
    items: list[NotificationResponse]


class AchievementResponse(BaseModel):
    id: UUID
    #: Null until earned. Redacted server-side rather than blurred in CSS, so
    #: the mystery survives devtools.
    name: str | None
    description: str | None
    earned: bool
    #: Share of players who have solved something and hold this, 0..1.
    rarity: float | None


class AchievementsResponse(BaseModel):
    earned: int
    total: int
    items: list[AchievementResponse]
    #: The player's rarest earned achievements — their bragging rights.
    rarest: list[AchievementResponse]


class StarResponse(BaseModel):
    """A boss kill (spec 031). Derived from the solve, never stored."""

    challenge_id: UUID
    #: The stable key (spec 059 §3) — what a client keys a star on.
    slug: str
    challenge_title: str
    zone_name: str
    tier: str
    #: 1 (Neighborhood) to 6 (Floor), so a client can order without the names.
    level: int
