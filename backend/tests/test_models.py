"""Schema-level guarantees for spec 002.

These test the database, not the application. Each rule below is enforced by a
constraint precisely because application-level checks lose races: two concurrent
requests can both read "this user has no party" before either writes.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.team import MembershipRole, RemovalReason, TeamMembership
from app.models.user import User, UserSource, UserStatus
from tests.factories import add_member, make_team, make_user


async def test_a_user_can_hold_only_one_active_membership(db_session: AsyncSession) -> None:
    player = await make_user(db_session)
    first_team = await make_team(db_session, await make_user(db_session))
    second_team = await make_team(db_session, await make_user(db_session))

    await add_member(db_session, first_team, player)

    with pytest.raises(IntegrityError):
        await add_member(db_session, second_team, player)


async def test_a_removed_member_may_join_another_party(db_session: AsyncSession) -> None:
    """Rosters stay open all event, so leaving and rejoining must work."""
    player = await make_user(db_session)
    first_team = await make_team(db_session, await make_user(db_session))
    second_team = await make_team(db_session, await make_user(db_session))

    membership = await add_member(db_session, first_team, player)
    membership.removed_at = datetime.now(UTC)
    membership.removal_reason = RemovalReason.LEFT
    await db_session.flush()

    rejoined = await add_member(db_session, second_team, player)

    assert rejoined.is_active
    assert not membership.is_active


async def test_membership_history_survives_removal(db_session: AsyncSession) -> None:
    """A kicked player's history is needed for anti-cheat review (spec 007)."""
    player = await make_user(db_session)
    team = await make_team(db_session, await make_user(db_session))
    membership = await add_member(db_session, team, player)

    membership.removed_at = datetime.now(UTC)
    membership.removal_reason = RemovalReason.KICKED
    await db_session.flush()

    rows = (
        (
            await db_session.execute(
                select(TeamMembership).where(TeamMembership.user_id == player.id)
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].removal_reason == RemovalReason.KICKED


async def test_emails_are_case_insensitively_unique(db_session: AsyncSession) -> None:
    """Otherwise a guest could register the Entra-linked address in another case."""
    await make_user(db_session, email="Rogue@example.com")

    with pytest.raises(IntegrityError):
        await make_user(db_session, email="rogue@example.com")


async def test_team_names_are_case_insensitively_unique(db_session: AsyncSession) -> None:
    leader = await make_user(db_session)
    other_leader = await make_user(db_session)
    await make_team(db_session, leader, name="Mimics")

    with pytest.raises(IntegrityError):
        await make_team(db_session, other_leader, name="mimics")


async def test_only_one_pending_join_request_per_user_and_party(
    db_session: AsyncSession,
) -> None:
    from app.models.team import JoinRequestStatus, TeamJoinRequest

    player = await make_user(db_session)
    team = await make_team(db_session, await make_user(db_session))

    first = TeamJoinRequest(team_id=team.id, user_id=player.id)
    db_session.add(first)
    await db_session.flush()

    # A savepoint, so undoing the expected failure does not also undo the party.
    savepoint = await db_session.begin_nested()
    db_session.add(TeamJoinRequest(team_id=team.id, user_id=player.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await savepoint.rollback()

    # A decided request must not block the player from asking again later.
    first.status = JoinRequestStatus.REJECTED
    first.decided_at = datetime.now(UTC)
    await db_session.flush()

    db_session.add(TeamJoinRequest(team_id=team.id, user_id=player.id))
    await db_session.flush()


async def test_event_config_is_a_singleton(db_session: AsyncSession) -> None:
    """A second event config would make "has the event started?" ambiguous."""
    db_session.add(EventConfig(id=uuid.uuid4(), name="Impostor Event"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_event_config_row_exists_from_the_migration(db_session: AsyncSession) -> None:
    config = await db_session.get(EventConfig, EVENT_CONFIG_ID)

    assert config is not None
    assert config.registration_open is True


async def test_unscheduled_event_reads_as_not_started(db_session: AsyncSession) -> None:
    """Null timestamps fail shut: an unscheduled event is closed, not open."""
    config = EventConfig(id=EVENT_CONFIG_ID, name="Unscheduled")

    assert config.has_started(datetime.now(UTC)) is False
    assert config.is_running(datetime.now(UTC)) is False


async def test_event_window_boundaries(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    config = EventConfig(
        id=EVENT_CONFIG_ID,
        name="Weekend Crawl",
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
    )

    assert config.has_started(now)
    assert config.is_running(now)
    assert not config.has_ended(now)
    assert config.has_ended(now + timedelta(hours=2))
    assert not config.is_running(now + timedelta(hours=2))


async def test_timestamps_are_timezone_aware(db_session: AsyncSession) -> None:
    """Naive timestamps across a multi-day event spanning DST are a data bug."""
    user = await make_user(db_session)
    await db_session.refresh(user)

    assert user.created_at.tzinfo is not None
    assert user.created_at.utcoffset() == timedelta(0)


async def test_guest_and_entra_users_share_one_table(db_session: AsyncSession) -> None:
    """Both login paths converge on one identity, so downstream code sees one shape."""
    guest = await make_user(db_session, source=UserSource.GUEST, status=UserStatus.PENDING_APPROVAL)
    employee = await make_user(
        db_session,
        source=UserSource.ENTRA,
        status=UserStatus.ACTIVE,
        entra_object_id=uuid.uuid4(),
    )

    users = (await db_session.execute(select(User).order_by(User.created_at))).scalars().all()

    assert {guest.id, employee.id} <= {u.id for u in users}
    assert guest.entra_object_id is None


async def test_leader_membership_is_created_with_the_party(db_session: AsyncSession) -> None:
    leader = await make_user(db_session)
    team = await make_team(db_session, leader)

    membership = (
        await db_session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id, TeamMembership.user_id == leader.id
            )
        )
    ).scalar_one()

    assert membership.role == MembershipRole.LEADER
    assert team.leader_user_id == leader.id


async def test_audit_log_metadata_column_is_named_metadata(db_session: AsyncSession) -> None:
    """The attribute is `meta` only because SQLAlchemy reserves `metadata`."""
    from app.models.audit import AuditLog

    admin = await make_user(db_session)
    entry = AuditLog(
        actor_user_id=admin.id,
        action="user.approve",
        target_type="user",
        target_id=admin.id,
        reason="Known attendee",
        meta={"source": "test"},
        request_id="req-123",
    )
    db_session.add(entry)
    await db_session.flush()

    stored = (
        await db_session.execute(
            text("SELECT metadata->>'source' FROM audit_log WHERE id = :id"),
            {"id": entry.id},
        )
    ).scalar()

    assert stored == "test"
