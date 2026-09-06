"""Test object factories.

Deliberately thin: they build valid rows with sensible defaults so a test can say
only what it actually cares about.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import MembershipRole, Team, TeamMembership, TeamVisibility
from app.models.user import User, UserRole, UserSource, UserStatus


async def make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    display_name: str = "Test Player",
    source: UserSource = UserSource.GUEST,
    status: UserStatus = UserStatus.ACTIVE,
    role: UserRole = UserRole.PLAYER,
    entra_object_id: uuid.UUID | None = None,
) -> User:
    user = User(
        email=email or f"player-{uuid.uuid4().hex[:12]}@example.test",
        display_name=display_name,
        source=source,
        status=status,
        role=role,
        entra_object_id=entra_object_id,
    )
    session.add(user)
    await session.flush()
    return user


async def make_team(
    session: AsyncSession,
    leader: User,
    *,
    name: str | None = None,
    visibility: TeamVisibility = TeamVisibility.PUBLIC,
    join_password_hash: str | None = None,
    max_members: int = 8,
) -> Team:
    team = Team(
        name=name or f"Party {uuid.uuid4().hex[:8]}",
        visibility=visibility,
        join_password_hash=join_password_hash,
        leader_user_id=leader.id,
        max_members=max_members,
    )
    session.add(team)
    await session.flush()
    await add_member(session, team, leader, role=MembershipRole.LEADER)
    return team


async def add_member(
    session: AsyncSession,
    team: Team,
    user: User,
    *,
    role: MembershipRole = MembershipRole.MEMBER,
) -> TeamMembership:
    membership = TeamMembership(
        team_id=team.id,
        user_id=user.id,
        role=role,
        joined_at=datetime.now(UTC),
    )
    session.add(membership)
    await session.flush()
    return membership
