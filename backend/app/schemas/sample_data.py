"""Response models for sample-data generation."""

from pydantic import BaseModel


class SampleDataSummary(BaseModel):
    """What the generator made, so the admin sees it landed."""

    categories: int
    challenges: int
    skills: int
    classes: int
    hints: int
    players: int
    teams: int
    solves: int
    gates: int
