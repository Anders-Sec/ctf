"""Model package.

Every model module is imported here so that ``Base.metadata`` is fully populated
by the time Alembic autogenerate or a test fixture looks at it. A model that is
not imported here is invisible to migrations.
"""

from app.models.audit import AuditLog
from app.models.auth import AuthSession, MagicLinkToken
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.challenge import (
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeArtifact,
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.hint import Hint, HintUnlock
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.team import (
    Team,
    TeamJoinRequest,
    TeamMembership,
)
from app.models.user import User

__all__ = [
    "EVENT_CONFIG_ID",
    "AuditLog",
    "AuthSession",
    "Base",
    "Category",
    "Challenge",
    "ChallengeAnswer",
    "ChallengeArtifact",
    "ChallengeState",
    "DecayBasis",
    "Difficulty",
    "MatchType",
    "PreReleaseState",
    "ScoreAdjustment",
    "ScoringMode",
    "Solve",
    "Submission",
    "EventConfig",
    "Hint",
    "HintUnlock",
    "MagicLinkToken",
    "Team",
    "TeamJoinRequest",
    "TeamMembership",
    "TimestampMixin",
    "User",
    "UUIDPrimaryKeyMixin",
]
