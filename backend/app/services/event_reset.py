"""Resetting an event's play data (spec 043).

Setting an event up means playing it a bit — solving a few challenges to check
they work, buying a hint to see the wording, letting the container spin up. That
test play then behaves exactly like real play: it banks XP, earns achievements,
and **pins the challenge**, because a solved challenge cannot be deleted.

This is how you take it back. Everything the players did can go; everything the
admins authored, and everyone's account, stays.

**Per group, not all or nothing.** Clearing solves is the one that unblocks
deletion, and is often all that is wanted. Picking some groups and not others can
leave stale-looking data — an achievement for a solve that no longer exists — but
never inconsistent data: every derived number (banked XP, ability scores, skill
levels, boss stars, the board) is computed at read time from whatever is left.

Groups rather than raw table names because a couple of them must move together,
and because the mapping is not obvious: clearing **loot** removes the awarded
boxes and unequips every worn title, but leaves ``loot_item`` alone — that table
is the catalogue a box draws from, not a per-player drop.
"""

import enum
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.assistant import (
    AssistantConversation,
    AssistantMessage,
    TermsAcceptance,
)
from app.models.character_class import ClassPreference
from app.models.email import EmailDelivery
from app.models.guardrail import AssistantFinding
from app.models.hint import HintUnlock
from app.models.instance import ChallengeInstance
from app.models.notification import AchievementAward, LootBox, Notification
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.player_event import PlayerEvent
from app.models.puzzle import PuzzleSession
from app.models.report import ChallengeReport
from app.models.signal import SignalDismissal
from app.models.user import User


class ResetGroup(enum.StrEnum):
    """What an admin can choose to clear."""

    SOLVES = "solves"
    SUBMISSIONS = "submissions"
    HINT_UNLOCKS = "hint_unlocks"
    SCORE_ADJUSTMENTS = "score_adjustments"
    ACHIEVEMENTS = "achievements"
    NOTIFICATIONS = "notifications"
    PLAYER_EVENTS = "player_events"
    LOOT = "loot"
    INSTANCES = "instances"
    REPORTS = "reports"
    SIGNAL_DISMISSALS = "signal_dismissals"
    ASSISTANT = "assistant"
    AI_LADDER = "ai_ladder"
    CLASS_CHOICES = "class_choices"
    PUZZLE_SESSIONS = "puzzle_sessions"
    EMAIL_DELIVERIES = "email_deliveries"


#: Group -> (label, the tables it counts). The label is what the confirm dialog
#: says, so it is written for an admin rather than for a schema.
GROUPS: dict[ResetGroup, tuple[str, list[type]]] = {
    ResetGroup.SOLVES: ("Solves", [Solve]),
    ResetGroup.SUBMISSIONS: ("Flag submissions", [Submission]),
    ResetGroup.HINT_UNLOCKS: ("Hint purchases", [HintUnlock]),
    ResetGroup.SCORE_ADJUSTMENTS: ("Manual score awards", [ScoreAdjustment]),
    ResetGroup.ACHIEVEMENTS: ("Earned achievements", [AchievementAward]),
    ResetGroup.NOTIFICATIONS: ("Notifications", [Notification]),
    ResetGroup.PLAYER_EVENTS: ("Platform events", [PlayerEvent]),
    #: The awarded boxes, not ``loot_item``: that table is the *catalogue* of
    #: titles a box can yield, authored content shared by every player. Even the
    #: model-generated entries are kept deliberately, to be reviewed and promoted
    #: into the authored list (spec 038).
    ResetGroup.LOOT: ("Loot boxes", [LootBox]),
    ResetGroup.INSTANCES: ("Container instances", [ChallengeInstance]),
    ResetGroup.REPORTS: ("Challenge reports", [ChallengeReport]),
    ResetGroup.SIGNAL_DISMISSALS: ("Anti-cheat review state", [SignalDismissal]),
    ResetGroup.ASSISTANT: (
        "AI assistant history",
        [AssistantMessage, AssistantFinding, AssistantConversation, TermsAcceptance],
    ),
    #: No table of its own — two columns on ``user``, counted as the players
    #: carrying them.
    ResetGroup.AI_LADDER: ("AI ladder progress", []),
    ResetGroup.CLASS_CHOICES: ("Class choices", [ClassPreference]),
    #: A player's play of a daily puzzle (spec 044) — guesses, groups found,
    #: letters typed, and whether they solved or lost it. **Not**
    #: ``challenge_puzzle``, which is the authored puzzle itself: the same
    #: distinction as Loot above, and the same trap in the naming.
    #:
    #: Its own group because clearing Solves alone leaves a *failed* session
    #: failed, and a re-run event would open with players still locked out of
    #: days they lost the first time round.
    ResetGroup.PUZZLE_SESSIONS: ("Puzzle play", [PuzzleSession]),
    #: Spec 055. Its own group so a reset between a rehearsal and the real event
    #: clears the rehearsal's sends rather than leaving them to muddy the
    #: failure rate on the Email Delivery page.
    ResetGroup.EMAIL_DELIVERIES: ("Email delivery log", [EmailDelivery]),
}


class ResetRejected(AppError):
    status_code = 422
    code = "reset_rejected"
    message = "That reset could not be run."


@dataclass
class GroupCount:
    group: ResetGroup
    label: str
    rows: int


@dataclass
class ResetResult:
    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


async def counts(db: AsyncSession) -> list[GroupCount]:
    """What each group currently holds, so a confirm dialog can say so.

    Reads only. This is the number an admin decides against, and it is the only
    thing between "reset" and an irreversible wipe of a dozen tables.
    """
    out: list[GroupCount] = []
    for group, (label, tables) in GROUPS.items():
        if group is ResetGroup.AI_LADDER:
            rows = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.ai_ladder_level.is_not(None) | User.ai_ladder_leaked_at.is_not(None))
            )
        else:
            rows = 0
            for table in tables:
                rows += int(await db.scalar(select(func.count()).select_from(table)) or 0)
        out.append(GroupCount(group=group, label=label, rows=int(rows or 0)))
    return out


async def reset(db: AsyncSession, groups: list[ResetGroup]) -> ResetResult:
    """Clear the chosen groups. Irreversible, and there is no undo anywhere."""
    if not groups:
        raise ResetRejected("Choose at least one thing to clear.")

    chosen = set(groups)
    result = ResetResult()

    # Nobody is wearing a title from a box that no longer exists. The item rows
    # themselves survive — they are the catalogue, not the drop — so this is
    # about what a player holds rather than about a dangling reference.
    if ResetGroup.LOOT in chosen:
        await db.execute(update(User).values(equipped_title_id=None))

    for group in GROUPS:
        if group not in chosen:
            continue
        _label, tables = GROUPS[group]
        for table in tables:
            deleted = await db.execute(table.__table__.delete())
            result.deleted[table.__tablename__] = deleted.rowcount or 0

    if ResetGroup.ASSISTANT in chosen:
        await db.execute(update(User).values(assistant_blocked=False))
    if ResetGroup.AI_LADDER in chosen:
        await db.execute(update(User).values(ai_ladder_level=None, ai_ladder_leaked_at=None))
    if ResetGroup.CLASS_CHOICES in chosen:
        await db.execute(update(User).values(character_class_id=None))

    await db.flush()
    return result


def parse_groups(raw: list[str] | None) -> list[ResetGroup]:
    """``None`` or an empty list is refused rather than read as "everything" —
    the difference between clearing one group and clearing all fourteen must
    never come down to a missing field."""
    if not raw:
        raise ResetRejected("Choose at least one thing to clear.")
    parsed: list[ResetGroup] = []
    for name in raw:
        try:
            parsed.append(ResetGroup(name))
        except ValueError as exc:
            raise ResetRejected(
                f"{name!r} is not something that can be cleared. One of: "
                + ", ".join(g.value for g in ResetGroup)
            ) from exc
    return parsed


#: Named so the omission is on purpose and reviewable, not an oversight.
#:
#: Users, teams, memberships and sessions — a reset means "the event has not
#: happened yet", not "these people do not exist", and nobody is logged out.
#: The audit log — including this reset's own entry; wiping it as part of an
#: audited operation would be the one deletion nobody could review.
#: Broadcasts — staff action, not play.
#: Everything authored: challenges, answers, hints, skills, zones, classes,
#: container templates, unlock requirements, achievements, event config.
NOT_TOUCHED = (
    "user",
    "team",
    "team_membership",
    "team_join_request",
    "auth_session",
    "audit_log",
    "broadcast_log",
    "challenge",
    "challenge_answer",
    "challenge_artifact",
    "challenge_skill",
    "category",
    "skill",
    "hint",
    "achievement",
    "character_class",
    "class_requirement",
    "container_template",
    "unlock_requirement",
    "event_config",
)
