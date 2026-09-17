"""Model package.

Every model module is imported here so that ``Base.metadata`` is fully populated
by the time Alembic autogenerate or a test fixture looks at it. A model that is
not imported here is invisible to migrations.
"""

from app.models.announcement import Announcement, AnnouncementAudience
from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.audit import AuditLog
from app.models.auth import AuthSession, MagicLinkToken
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.challenge import (
    Ability,
    BossTier,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeArtifact,
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    RequirementType,
    ScoringMode,
    SkillKind,
    UnlockRequirement,
)
from app.models.character_class import (
    CharacterClass,
    ClassPreference,
    ClassRequirement,
    Rarity,
)
from app.models.email import EmailDelivery, EmailKind, EmailStatus
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.guardrail import (
    AssistantFinding,
    FindingAction,
    GuardrailLayer,
    Severity,
)
from app.models.hint import Hint, HintUnlock
from app.models.instance import (
    ChallengeInstance,
    ChallengeInstanceAnswer,
    ContainerTemplate,
    EgressPolicy,
    InstanceProtocol,
    InstanceStatus,
)
from app.models.notification import (
    Achievement,
    AchievementAward,
    BroadcastLog,
    Notification,
    NotificationKind,
)
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.player_event import PlayerEvent, PlayerEventKind
from app.models.puzzle import ChallengePuzzle, PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.report import ChallengeReport, ReportStatus
from app.models.signal import SignalDismissal
from app.models.skill import ChallengeSkill, Skill
from app.models.team import (
    Team,
    TeamJoinRequest,
    TeamMembership,
)
from app.models.theme_unlock import UnlockSource, UserThemeUnlock
from app.models.user import User

__all__ = [
    "BroadcastLog",
    "BossTier",
    "NotificationKind",
    "Notification",
    "AchievementAward",
    "Achievement",
    "EVENT_CONFIG_ID",
    "AssistantConversation",
    "AssistantFinding",
    "AssistantMessage",
    "Announcement",
    "AnnouncementAudience",
    "AuditLog",
    "UnlockSource",
    "UserThemeUnlock",
    "AuthSession",
    "Base",
    "Ability",
    "Category",
    "CharacterClass",
    "ClassPreference",
    "ClassRequirement",
    "Rarity",
    "ChallengeInstance",
    "ChallengeInstanceAnswer",
    "ContainerTemplate",
    "ChallengeReport",
    "Challenge",
    "ChallengeAnswer",
    "ChallengeArtifact",
    "UnlockRequirement",
    "ChallengeState",
    "DecayBasis",
    "Difficulty",
    "FindingAction",
    "GuardrailLayer",
    "MatchType",
    "MessageRole",
    "Severity",
    "PreReleaseState",
    "RequirementType",
    "ReportStatus",
    "PlayerEvent",
    "PlayerEventKind",
    "ChallengePuzzle",
    "PuzzleKind",
    "PuzzleSession",
    "PuzzleStatus",
    "ScoreAdjustment",
    "ScoringMode",
    "SignalDismissal",
    "Skill",
    "SkillKind",
    "ChallengeSkill",
    "Solve",
    "Submission",
    "EgressPolicy",
    "EventConfig",
    "Hint",
    "InstanceProtocol",
    "InstanceStatus",
    "EmailDelivery",
    "EmailKind",
    "EmailStatus",
    "HintUnlock",
    "MagicLinkToken",
    "Team",
    "TeamJoinRequest",
    "TeamMembership",
    "TimestampMixin",
    "User",
    "UUIDPrimaryKeyMixin",
]
