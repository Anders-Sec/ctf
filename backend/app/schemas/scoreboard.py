"""Response models for the scoreboard."""

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
    """A compact header: where you stand, and where your party stands."""

    rank: int | None
    score: int
    level: int
    player_count: int
    team_rank: int | None
    team_score: int | None
    team_level: int | None
    team_count: int
