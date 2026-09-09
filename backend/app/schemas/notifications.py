"""Notification and achievement responses (spec 028)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
