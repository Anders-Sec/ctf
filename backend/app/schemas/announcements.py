"""Admin announcements (spec 032)."""

from pydantic import BaseModel, Field


class AnnouncementRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=2000)
    link: str | None = Field(default=None, max_length=500)


class AnnouncementResult(BaseModel):
    #: How many players it reached. Zero is a real answer when nobody is active.
    recipients: int
