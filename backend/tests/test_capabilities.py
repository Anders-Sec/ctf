"""The capability matrix from spec 002, tested exhaustively.

Every combination of role, account status and event phase, rather than a
representative sample. This is the gate standing between an unapproved stranger
and the whole platform, and a hole in one cell is a hole in the event.
"""

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services.capabilities import (
    REASON_DISABLED,
    REASON_ENDED,
    REASON_NOT_STARTED,
    REASON_PENDING_APPROVAL,
    resolve_capabilities,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

EVENTS = {
    "unscheduled": EventConfig(id=EVENT_CONFIG_ID, name="Unscheduled"),
    "before": EventConfig(
        id=EVENT_CONFIG_ID,
        name="Upcoming",
        starts_at=NOW + timedelta(hours=1),
        ends_at=NOW + timedelta(days=2),
    ),
    "running": EventConfig(
        id=EVENT_CONFIG_ID,
        name="Running",
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(days=2),
    ),
    "ended": EventConfig(
        id=EVENT_CONFIG_ID,
        name="Finished",
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW - timedelta(hours=1),
    ),
}


def make(role: UserRole, status: UserStatus) -> User:
    return User(
        email="matrix@example.com",
        display_name="Matrix",
        source=UserSource.GUEST,
        role=role,
        status=status,
    )


ALL_ROLES = list(UserRole)
ALL_PHASES = list(EVENTS)


@pytest.mark.parametrize(("role", "phase"), list(itertools.product(ALL_ROLES, ALL_PHASES)))
def test_disabled_accounts_can_do_nothing(role: UserRole, phase: str) -> None:
    """Disabled beats every role. An admin who is disabled is not an admin."""
    caps = resolve_capabilities(make(role, UserStatus.DISABLED), EVENTS[phase], NOW)

    assert not any(
        (caps.manage_party, caps.play, caps.view_scoreboard, caps.view_admin, caps.administer)
    )
    assert caps.blocked_reason == REASON_DISABLED


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_pending_guests_may_organise_a_party_but_not_play(phase: str) -> None:
    """Only gameplay waits on approval, so a party can be picked the night before."""
    caps = resolve_capabilities(
        make(UserRole.PLAYER, UserStatus.PENDING_APPROVAL), EVENTS[phase], NOW
    )

    assert caps.manage_party
    assert not caps.play
    assert not caps.view_scoreboard
    assert caps.blocked_reason == REASON_PENDING_APPROVAL


@pytest.mark.parametrize(
    ("phase", "expected_play"),
    [("unscheduled", False), ("before", False), ("running", True), ("ended", False)],
)
def test_active_players_only_play_while_the_event_runs(phase: str, expected_play: bool) -> None:
    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), EVENTS[phase], NOW)

    assert caps.play is expected_play
    assert caps.manage_party


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_staff_bypass_the_event_clock(phase: str) -> None:
    """Someone has to be able to test a challenge at 08:00 for a 09:00 start."""
    for role in (UserRole.ORGANIZER, UserRole.ADMIN):
        caps = resolve_capabilities(make(role, UserStatus.ACTIVE), EVENTS[phase], NOW)

        assert caps.play, f"{role} blocked during {phase}"
        assert caps.view_scoreboard


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_organizers_can_look_but_not_touch(phase: str) -> None:
    """Staff watching for broken challenges must not be able to rewrite scores."""
    caps = resolve_capabilities(make(UserRole.ORGANIZER, UserStatus.ACTIVE), EVENTS[phase], NOW)

    assert caps.view_admin
    assert not caps.administer


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_only_admins_administer(phase: str) -> None:
    admin = resolve_capabilities(make(UserRole.ADMIN, UserStatus.ACTIVE), EVENTS[phase], NOW)
    player = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), EVENTS[phase], NOW)

    assert admin.administer
    assert not player.administer
    assert not player.view_admin


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_pending_staff_are_still_pending(phase: str) -> None:
    """An unapproved account does not get to play by being handed a role."""
    caps = resolve_capabilities(
        make(UserRole.ADMIN, UserStatus.PENDING_APPROVAL), EVENTS[phase], NOW
    )

    assert not caps.play
    assert caps.blocked_reason == REASON_PENDING_APPROVAL


def test_a_missing_event_config_fails_shut() -> None:
    """No configuration must read as closed, never as wide open."""
    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), None, NOW)

    assert not caps.play
    assert caps.blocked_reason == REASON_NOT_STARTED


def test_blocked_reason_distinguishes_not_started_from_ended() -> None:
    """The SPA renders a countdown for one and a results screen for the other."""
    before = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), EVENTS["before"], NOW)
    after = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), EVENTS["ended"], NOW)

    assert before.blocked_reason == REASON_NOT_STARTED
    assert after.blocked_reason == REASON_ENDED


def test_the_exact_start_instant_counts_as_started() -> None:
    """An off-by-one here is 200 players refreshing at 09:00:00 and seeing a lock."""
    event = EventConfig(
        id=EVENT_CONFIG_ID, name="Boundary", starts_at=NOW, ends_at=NOW + timedelta(days=1)
    )

    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), event, NOW)

    assert caps.play


def test_the_exact_end_instant_counts_as_ended() -> None:
    event = EventConfig(
        id=EVENT_CONFIG_ID, name="Boundary", starts_at=NOW - timedelta(days=1), ends_at=NOW
    )

    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), event, NOW)

    assert not caps.play
    assert caps.blocked_reason == REASON_ENDED


def test_an_event_with_no_end_runs_indefinitely() -> None:
    event = EventConfig(id=EVENT_CONFIG_ID, name="Open ended", starts_at=NOW - timedelta(hours=1))

    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), event, NOW)

    assert caps.play


def test_capabilities_serialise_for_the_frontend() -> None:
    caps = resolve_capabilities(make(UserRole.PLAYER, UserStatus.ACTIVE), EVENTS["running"], NOW)

    payload = caps.to_dict()

    assert set(payload) == {
        "manage_party",
        "play",
        "view_scoreboard",
        "view_admin",
        "administer",
        "blocked_reason",
    }
