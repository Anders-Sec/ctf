"""Portrait payloads (spec 074).

Read this file as the enforcement of §1: there is **no field here that carries
prompt text**, in either direction. ``StartJobRequest`` takes a map of axis to
trait key and pydantic drops anything else; ``TraitOut`` carries a key and a
label and deliberately not the fragment.
"""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.avatar_trait import JobState


class TraitOut(BaseModel):
    """One option, as the builder sees it.

    ``prompt_fragment`` is absent on purpose and its absence is a test.
    """

    key: str
    label: str


class AxisOut(BaseModel):
    axis: str
    options: list[TraitOut]


class BuilderOut(BaseModel):
    #: False when the host is off, unconfigured, or its breaker is open. The
    #: frontend hides the whole feature behind this rather than offering a
    #: button that fails (spec 074 §7).
    available: bool
    remaining: int
    candidates_per_job: int
    #: The player's real class, pre-selected — what ties a portrait to
    #: progression rather than to a costume box.
    default_class_look: str | None
    axes: list[AxisOut]


class StartJobRequest(BaseModel):
    """``{axis: trait_key}`` and nothing else.

    Keys are short and pattern-matched, so this cannot be used as a smuggling
    channel for prose even before ``resolve_traits`` refuses to find it.
    """

    traits: dict[str, str] = Field(default_factory=dict, max_length=8)


class CandidateOut(BaseModel):
    id: UUID
    seed: int


class JobOut(BaseModel):
    id: UUID
    state: JobState
    #: A coarse reason from the image client, or null.
    error: str | None
    candidates: list[CandidateOut]
