"""Roster aggregates and the per-player detail (spec 052).

The endpoints in ``app.api.routes.admin`` were built in spec 002 and are mostly
complete; what was missing is everything the page needed to be worth opening.
This module holds the read side of that.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.avatar_trait import AvatarJob, JobState
from app.models.challenge import Challenge
from app.models.character_class import CharacterClass
from app.models.hint import HintUnlock
from app.models.notification import AchievementAward
from app.models.play import Solve, Submission
from app.models.team import MembershipRole, Team, TeamMembership
from app.models.user import User
from app.services import theme_unlocks
from app.services.scoring import level_for_xp


async def roster_extras(
    db: AsyncSession, user_ids: list[UUID]
) -> tuple[dict[UUID, str], dict[UUID, int], dict[UUID, int]]:
    """Party, solve count and XP for a page of the roster.

    Three grouped queries for the whole page rather than three per row — at 200
    users an N+1 here is 600 round trips for a table nobody would wait for.
    """
    if not user_ids:
        return {}, {}, {}

    parties = dict(
        (
            await db.execute(
                select(TeamMembership.user_id, Team.name)
                .join(Team, Team.id == TeamMembership.team_id)
                .where(
                    TeamMembership.user_id.in_(user_ids),
                    TeamMembership.removed_at.is_(None),
                    Team.disbanded_at.is_(None),
                )
            )
        ).all()
    )

    solve_rows = (
        await db.execute(
            select(Solve.user_id, func.count(), func.coalesce(func.sum(Solve.xp_awarded), 0))
            .where(Solve.user_id.in_(user_ids))
            .group_by(Solve.user_id)
        )
    ).all()

    counts = {user_id: int(count) for user_id, count, _ in solve_rows}
    xp = {user_id: int(total) for user_id, _, total in solve_rows}
    return parties, counts, xp


async def _party_history(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Every membership, including the ended ones.

    Rows are never hard-deleted (spec 002), and that history is exactly what is
    needed when adjudicating a complaint about a kick.
    """
    rows = (
        await db.execute(
            select(TeamMembership, Team.name)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(TeamMembership.user_id == user_id)
            .order_by(TeamMembership.joined_at.desc())
        )
    ).all()

    return [
        {
            "team_id": membership.team_id,
            "team_name": name,
            "role": (
                membership.role.value
                if isinstance(membership.role, MembershipRole)
                else str(membership.role)
            ),
            "joined_at": membership.joined_at,
            "removed_at": membership.removed_at,
            "removal_reason": (
                membership.removal_reason.value if membership.removal_reason else None
            ),
        }
        for membership, name in rows
    ]


async def _recent_activity(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Submission, Challenge.title)
            .outerjoin(Challenge, Challenge.id == Submission.challenge_id)
            .where(Submission.user_id == user_id)
            .order_by(Submission.created_at.desc())
            .limit(25)
        )
    ).all()

    return [
        {
            "challenge_id": submission.challenge_id,
            "challenge_title": title,
            "is_correct": submission.is_correct,
            "created_at": submission.created_at,
        }
        # Deliberately no `submitted_value`: this panel is read during a support
        # conversation, often with the player looking at the screen, and it has
        # no business showing what anybody typed into a flag box.
        for submission, title in rows
    ]


async def _current_wall(db: AsyncSession, user_id: UUID) -> str | None:
    """The challenge most recently attempted and not solved."""
    solved = select(Solve.challenge_id).where(Solve.user_id == user_id)
    row = (
        await db.execute(
            select(Challenge.title)
            .join(Submission, Submission.challenge_id == Challenge.id)
            .where(Submission.user_id == user_id, Submission.challenge_id.not_in(solved))
            .order_by(Submission.created_at.desc())
            .limit(1)
        )
    ).first()
    return row[0] if row else None


async def detail(db: AsyncSession, user: User) -> dict[str, Any]:
    xp = int(
        await db.scalar(
            select(func.coalesce(func.sum(Solve.xp_awarded), 0)).where(Solve.user_id == user.id)
        )
        or 0
    )
    hints_used = int(
        await db.scalar(
            select(func.count()).select_from(HintUnlock).where(HintUnlock.user_id == user.id)
        )
        or 0
    )
    achievements = int(
        await db.scalar(
            select(func.count())
            .select_from(AchievementAward)
            .where(AchievementAward.user_id == user.id)
        )
        or 0
    )
    class_name = None
    if user.character_class_id:
        class_name = await db.scalar(
            select(CharacterClass.name).where(CharacterClass.id == user.character_class_id)
        )

    return {
        "unlocked_themes": await theme_unlocks.held_by(db, user.id),
        # The secret ones only: the everyday themes are already everybody's, so
        # granting one is not a reward (spec 058 §5.1).
        "grantable_themes": theme_unlocks.grantable(),
        "entra_object_id": user.entra_object_id,
        "approved_by_name": (
            await db.scalar(select(User.display_name).where(User.id == user.approved_by_user_id))
            if user.approved_by_user_id
            else None
        ),
        "disabled_reason": user.disabled_reason,
        "assistant_blocked": user.assistant_blocked,
        # Jobs that reached the model, so a refused or unreachable one
        # does not read as a portrait they spent.
        "portraits_used": int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(AvatarJob)
                    .where(AvatarJob.user_id == user.id, AvatarJob.state != JobState.FAILED)
                )
            ).scalar_one()
        ),
        "portrait_grant": user.portrait_grant,
        "level": level_for_xp(xp, get_settings().xp_level_base),
        "hints_used": hints_used,
        "achievement_count": achievements,
        "class_name": class_name,
        "parties": await _party_history(db, user.id),
        "recent_activity": await _recent_activity(db, user.id),
        "current_wall": await _current_wall(db, user.id),
    }
