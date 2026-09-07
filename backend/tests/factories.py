"""Test object factories.

Deliberately thin: they build valid rows with sensible defaults so a test can say
only what it actually cares about.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    DecayBasis,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.instance import ContainerTemplate
from app.models.play import Solve
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
        email=email or f"player-{uuid.uuid4().hex[:12]}@example.com",
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


async def make_category(
    session: AsyncSession, *, name: str | None = None, display_order: int = 0
) -> Category:
    suffix = uuid.uuid4().hex[:8]
    category = Category(
        name=name or f"Category {suffix}",
        slug=(name or f"category-{suffix}").lower().replace(" ", "-"),
        display_order=display_order,
    )
    session.add(category)
    await session.flush()
    return category


async def make_challenge(
    session: AsyncSession,
    *,
    category: Category | None = None,
    title: str | None = None,
    state: ChallengeState = ChallengeState.PUBLISHED,
    release_at: datetime | None = None,
    pre_release_state: PreReleaseState = PreReleaseState.HIDDEN,
    initial_points: int = 500,
    minimum_points: int = 100,
    decay_threshold: int = 40,
    scoring: ScoringMode = ScoringMode.DYNAMIC,
    decay_basis: DecayBasis = DecayBasis.PLAYERS,
    max_attempts: int | None = None,
    body: str = "Find the flag.",
    answers: list[tuple[MatchType, str]] | None = None,
) -> Challenge:
    suffix = uuid.uuid4().hex[:8]
    category = category or await make_category(session)
    challenge = Challenge(
        title=title or f"Challenge {suffix}",
        slug=f"challenge-{suffix}",
        category_id=category.id,
        body=body,
        state=state,
        release_at=release_at,
        pre_release_state=pre_release_state,
        initial_points=initial_points,
        minimum_points=minimum_points,
        decay_threshold=decay_threshold,
        scoring=scoring,
        decay_basis=decay_basis,
        max_attempts=max_attempts,
    )
    session.add(challenge)
    await session.flush()

    for order, (match_type, value) in enumerate(answers or [(MatchType.EXACT, "flag{correct}")]):
        session.add(
            ChallengeAnswer(
                challenge_id=challenge.id,
                match_type=match_type,
                value=value,
                options={},
                display_order=order,
            )
        )
    await session.flush()
    return challenge


async def record_solve(
    session: AsyncSession,
    user: User,
    challenge: Challenge,
    *,
    team: Team | None = None,
) -> Solve:
    solve = Solve(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_solve=team.id if team else None,
        submitted_at=datetime.now(UTC),
    )
    session.add(solve)
    await session.flush()
    return solve


async def make_template(
    session: AsyncSession,
    *,
    name: str = "Demo Target",
    image: str = "ghcr.io/anders-sec/ctf-demo",
    injects_answer: bool = True,
    ttl_seconds: int = 3600,
) -> ContainerTemplate:
    template = ContainerTemplate(
        name=name,
        image=image,
        image_tag="v1",
        container_port=8080,
        injects_answer=injects_answer,
        ttl_seconds=ttl_seconds,
    )
    session.add(template)
    await session.flush()
    return template


async def make_container_challenge(
    session: AsyncSession,
    template: ContainerTemplate,
    **kwargs,
) -> Challenge:
    """A published challenge wired to a container template."""
    challenge = await make_challenge(session, **kwargs)
    challenge.container_template_id = template.id
    await session.flush()
    return challenge
