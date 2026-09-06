"""Concurrent party joins, against real parallel transactions.

The rest of the suite runs inside one rolled-back transaction, which cannot
express two clients racing. These tests open genuinely separate connections and
commit, then clean up after themselves — the whole point is to prove that the
row lock, not application logic, is what keeps capacity correct.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models.audit import AuditLog
from app.models.team import MembershipRole, Team, TeamMembership
from app.models.user import User, UserSource, UserStatus
from app.services import teams as team_service


@pytest.fixture
async def committed_sessionmaker(
    settings: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _make_committed_user(maker: async_sessionmaker[AsyncSession], label: str) -> User:
    async with maker() as session:
        user = User(
            email=f"{label}-{datetime.now(UTC).timestamp()}@example.com",
            display_name=label,
            source=UserSource.GUEST,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.commit()
        return user


async def _cleanup(maker: async_sessionmaker[AsyncSession], user_ids: list, team_ids: list) -> None:
    async with maker() as session:
        await session.execute(delete(AuditLog).where(AuditLog.target_id.in_(team_ids)))
        await session.execute(delete(TeamMembership).where(TeamMembership.team_id.in_(team_ids)))
        await session.execute(delete(Team).where(Team.id.in_(team_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def test_the_row_lock_serialises_two_players_racing_for_the_last_slot(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Seven members plus two simultaneous joins must not make a party of nine.

    The ordering is forced rather than hoped for: the second joiner is started
    while the first still holds the lock, and the test asserts that it *blocks*
    until the first commits. Two joins fired with `gather` would interleave by
    luck and pass even with the lock removed, which proves nothing.
    """
    maker = committed_sessionmaker
    leader = await _make_committed_user(maker, "leader")
    fillers = [await _make_committed_user(maker, f"filler{i}") for i in range(6)]
    first_racer = await _make_committed_user(maker, "racer-a")
    second_racer = await _make_committed_user(maker, "racer-b")

    team_id = await _make_committed_team(maker, leader, fillers)

    try:
        first_session = maker()
        second_result: list[str] = []

        async def second_join() -> None:
            async with maker() as session:
                try:
                    await team_service.join_team(session, second_racer, team_id)
                    await session.commit()
                    second_result.append("joined")
                except team_service.TeamFull:
                    await session.rollback()
                    second_result.append("full")

        try:
            # Take the lock and hold it, without committing.
            await team_service.join_team(first_session, first_racer, team_id)

            waiter = asyncio.create_task(second_join())
            # Blocked on the row lock: it must not have decided anything yet.
            done, _ = await asyncio.wait({waiter}, timeout=1.0)
            assert not done, "second joiner was not blocked by the row lock"

            await first_session.commit()

            await asyncio.wait_for(waiter, timeout=5.0)
        finally:
            await first_session.close()

        # The second joiner now sees a full party rather than making it nine.
        assert second_result == ["full"]

        async with maker() as session:
            count = len(
                (
                    await session.execute(
                        select(TeamMembership).where(
                            TeamMembership.team_id == team_id,
                            TeamMembership.removed_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert count == 8
    finally:
        await _cleanup(
            maker,
            [leader.id, *[f.id for f in fillers], first_racer.id, second_racer.id],
            [team_id],
        )


async def _make_committed_team(
    maker: async_sessionmaker[AsyncSession], leader: User, fillers: list[User]
):
    async with maker() as session:
        team = Team(
            name=f"Race {datetime.now(UTC).timestamp()}",
            visibility="public",
            leader_user_id=leader.id,
        )
        session.add(team)
        await session.flush()
        session.add(
            TeamMembership(
                team_id=team.id,
                user_id=leader.id,
                role=MembershipRole.LEADER,
                joined_at=datetime.now(UTC),
            )
        )
        for filler in fillers:
            session.add(
                TeamMembership(team_id=team.id, user_id=filler.id, joined_at=datetime.now(UTC))
            )
        await session.commit()
        return team.id


async def test_one_player_double_clicking_join_joins_once(
    committed_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The partial unique index is what catches this, not a read-then-write check."""
    maker = committed_sessionmaker
    leader = await _make_committed_user(maker, "leader2")
    joiner = await _make_committed_user(maker, "eager")

    async with maker() as session:
        team = Team(
            name=f"Double {datetime.now(UTC).timestamp()}",
            visibility="public",
            leader_user_id=leader.id,
        )
        session.add(team)
        await session.flush()
        session.add(
            TeamMembership(
                team_id=team.id,
                user_id=leader.id,
                role=MembershipRole.LEADER,
                joined_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async def attempt() -> str:
        async with maker() as session:
            try:
                await team_service.join_team(session, joiner, team.id)
                await session.commit()
                return "joined"
            except (team_service.AlreadyInParty, IntegrityError):
                await session.rollback()
                return "rejected"

    try:
        results = await asyncio.gather(attempt(), attempt())

        assert results.count("joined") == 1, results

        async with maker() as session:
            active = (
                (
                    await session.execute(
                        select(TeamMembership).where(
                            TeamMembership.user_id == joiner.id,
                            TeamMembership.removed_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(active) == 1
    finally:
        await _cleanup(maker, [leader.id, joiner.id], [team.id])
