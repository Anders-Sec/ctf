"""What a party has claimed, zone by zone (spec 067).

The union rule made visible: spec 005 scores a challenge **once per party**
however many members solve it, so the bar has to move once too. And the payload
is strategy rather than flavour, so it is members only — the reconnaissance test
is the one that matters most here.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, ScoringMode
from app.models.user import UserRole, UserStatus
from tests.factories import (
    add_member,
    make_category,
    make_challenge,
    make_team,
    make_user,
    record_solve,
)

pytestmark = pytest.mark.usefixtures("running_event")


async def signed_in(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def zone(db_session, name: str):
    """Suffixed: the test database carries the real seeded categories."""
    return await make_category(db_session, name=f"{name} {uuid.uuid4().hex[:6]}")


def find(body, zone_name: str):
    return next(row for row in body["zones"] if row["name"] == zone_name)


class TestCoverage:
    async def test_two_members_on_one_challenge_move_the_bar_once(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The union rule, made visible. Size buys speed, never a higher ceiling."""
        web = await zone(db_session, "Web")
        shared = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="The Mimics")
        other = await make_user(db_session, display_name="Rin")
        await add_member(db_session, party, other)

        await record_solve(db_session, leader, shared, team=party)
        await record_solve(db_session, other, shared, team=party)

        body = (await client.get(f"/api/teams/{party.id}/progress")).json()

        assert find(body, web.name)["cleared"] == 1
        assert find(body, web.name)["total"] == 2

    async def test_it_names_the_earliest_solver(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The one spec 005's union credits — and the one to go and ask."""
        web = await zone(db_session, "Web")
        challenge = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="The Mimics")
        first = await make_user(db_session, display_name="Rin")
        await add_member(db_session, party, first)

        early = await record_solve(db_session, first, challenge, team=party)
        late = await record_solve(db_session, leader, challenge, team=party)
        # Both fixed and both in the past, an hour apart. This used to set the
        # later one with `.replace(hour=(hour + 1) % 24)`, which at 23:00 wraps
        # to midnight **the same day** — 23 hours earlier, not an hour later. It
        # passed everywhere except a CI run that happened to start in the last
        # hour of the UTC day.
        base = datetime.now(UTC).replace(tzinfo=None, microsecond=0) - timedelta(hours=2)
        early.submitted_at = base
        late.submitted_at = base + timedelta(hours=1)
        await db_session.flush()

        body = (await client.get(f"/api/teams/{party.id}/progress")).json()

        assert body["solved_by"][str(challenge.id)] == "Rin"

    async def test_an_unclaimed_challenge_is_absent_from_solved_by(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        web = await zone(db_session, "Web")
        untouched = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="The Mimics")

        body = (await client.get(f"/api/teams/{party.id}/progress")).json()

        assert str(untouched.id) not in body["solved_by"]
        assert find(body, web.name)["cleared"] == 0

    async def test_a_departed_member_takes_their_solves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The same roster the score and the stars are taken over."""
        web = await zone(db_session, "Web")
        theirs = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="Shrinking")
        leaver = await make_user(db_session, display_name="Leaver")
        membership = await add_member(db_session, party, leaver)
        await record_solve(db_session, leaver, theirs, team=party)

        before = (await client.get(f"/api/teams/{party.id}/progress")).json()
        assert find(before, web.name)["cleared"] == 1

        membership.removed_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.flush()

        after = (await client.get(f"/api/teams/{party.id}/progress")).json()
        assert find(after, web.name)["cleared"] == 0
        assert after["solved_by"] == {}

    async def test_a_sealed_zone_is_marked(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        vaults = await zone(db_session, "Vaults")
        await make_challenge(
            db_session, category=vaults, state=ChallengeState.LOCKED, scoring=ScoringMode.STATIC
        )

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="The Mimics")

        body = (await client.get(f"/api/teams/{party.id}/progress")).json()

        row = find(body, vaults.name)
        assert row["sealed"] is True
        # It still counts toward the total: knowing there is more is the point.
        assert row["total"] == 1

    async def test_a_zone_with_one_open_challenge_is_not_sealed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A zone open to the party is a zone the party can work on (§7.1)."""
        mixed = await zone(db_session, "Mixed")
        await make_challenge(
            db_session, category=mixed, state=ChallengeState.LOCKED, scoring=ScoringMode.STATIC
        )
        await make_challenge(db_session, category=mixed, scoring=ScoringMode.STATIC)

        leader = await signed_in(db_session, client, sign_in, display_name="Grix")
        party = await make_team(db_session, leader, name="The Mimics")

        body = (await client.get(f"/api/teams/{party.id}/progress")).json()

        assert find(body, mixed.name)["sealed"] is False
        assert find(body, mixed.name)["total"] == 2


class TestItIsMembersOnly:
    """Another party's coverage is reconnaissance, not a view (spec 067 §3)."""

    async def test_a_non_member_gets_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        stranger_leader = await make_user(db_session, display_name="Theirs")
        theirs = await make_team(db_session, stranger_leader, name="Rivals")

        me = await signed_in(db_session, client, sign_in, display_name="Nosy")
        await make_team(db_session, me, name="Mine")

        response = await client.get(f"/api/teams/{theirs.id}/progress")

        # A 404 rather than a 403: the refusal must not confirm the party exists
        # to somebody probing for it.
        assert response.status_code == 404

    async def test_staff_get_the_same_refusal(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """This is about membership, not rank."""
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Somebody Else's")
        await signed_in(db_session, client, sign_in, role=UserRole.ADMIN)

        assert (await client.get(f"/api/teams/{party.id}/progress")).status_code == 404

    async def test_a_removed_member_loses_access(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Was Mine")
        me = await signed_in(db_session, client, sign_in, display_name="Kicked")
        membership = await add_member(db_session, party, me)

        assert (await client.get(f"/api/teams/{party.id}/progress")).status_code == 200

        membership.removed_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.flush()

        assert (await client.get(f"/api/teams/{party.id}/progress")).status_code == 404
