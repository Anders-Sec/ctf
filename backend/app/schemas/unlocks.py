"""Admin request/response models for unlock requirements (spec 017)."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import RequirementType


class AdminRequirementResponse(BaseModel):
    """A requirement as an admin edits it — the stored row, not a player's view."""

    id: UUID
    requirement_type: RequirementType
    challenge_id: UUID | None
    category_id: UUID | None
    required_challenge_id: UUID | None
    required_skill_id: UUID | None
    required_category_id: UUID | None
    threshold: int | None


class CreateRequirementRequest(BaseModel):
    """Fields not used by the chosen type must be left out — the service refuses
    a row carrying values its type would never read."""

    requirement_type: RequirementType
    required_challenge_id: UUID | None = None
    required_skill_id: UUID | None = None
    required_category_id: UUID | None = None
    threshold: int | None = Field(default=None, ge=1)
