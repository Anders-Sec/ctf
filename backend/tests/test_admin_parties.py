"""Admin control over parties (spec 053)."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import JoinRequestStatus, RemovalReason, Team, TeamJoinRequest, TeamMembership
from app.models.user import UserRole, UserStatus
from app.services.admin_parties import MAX_MEMBERS_CEILING
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve


async def admin(db_session: AsyncSession, client: AsyncClient, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def membership_for(db_session: AsyncSession, user_id) -> TeamMembership | None:
    return (
        await db_session.execute(
            select(TeamMembership).where(
                TeamMembership.user_id == user_id, TeamMembership.removed_at.is_(None)
            )
        )
    ).scalar_one_or_none()


class TestMoving:
    async def test_it_moves_a_member_between_parties(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        source = await make_team(db_session, leader, name="Source")
        mover = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, source, mover)
        other_leader = await make_user(db_session, status=UserStatus.ACTIVE)
        destination = await make_team(db_session, other_leader, name="Destination")

        response = await client.post(
            f"/api/admin/parties/members/{mover.id}/move",
            json={"to_team_id": str(destination.id), "reason": "Joined the wrong one"},
        )

        assert response.status_code == 200
        current = await membership_for(db_session, mover.id)
        assert current is not None
        assert current.team_id == destination.id

    async def test_the_old_membership_is_closed_not_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The history is needed for anti-cheat review and for explaining a
        decision later (spec 002)."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        source = await make_team(db_session, leader, name="Old")
        mover = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, source, mover)
        destination = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="New"
        )

        await client.post(
            f"/api/admin/parties/members/{mover.id}/move",
            json={"to_team_id": str(destination.id)},
        )

        rows = (
            (
                await db_session.execute(
                    select(TeamMembership).where(
                        TeamMembership.user_id == mover.id,
                        TeamMembership.team_id == source.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].removed_at is not None
        assert rows[0].removal_reason == RemovalReason.ADMIN

    async def test_a_move_into_a_full_party_leaves_them_where_they_were(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Atomic: two steps could leave the player in neither party."""
        await admin(db_session, client, sign_in)
        source = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Roomy"
        )
        mover = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, source, mover)

        full_leader = await make_user(db_session, status=UserStatus.ACTIVE)
        full = await make_team(db_session, full_leader, name="Full", max_members=1)

        response = await client.post(
            f"/api/admin/parties/members/{mover.id}/move",
            json={"to_team_id": str(full.id)},
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "party_full"
        current = await membership_for(db_session, mover.id)
        assert current is not None and current.team_id == source.id

    async def test_moving_a_leader_is_refused_and_names_the_fix(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Silently promoting somebody else changes a social structure nobody
        asked to change."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, leader, name="Theirs")
        destination = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Elsewhere"
        )

        response = await client.post(
            f"/api/admin/parties/members/{leader.id}/move",
            json={"to_team_id": str(destination.id)},
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "is_leader"

    async def test_solves_do_not_move_with_the_player(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A party's standing is an aggregate over its current members, so the
        contribution follows automatically and there is nothing to recompute.
        `team_id_at_solve` is history, not score, and is untouched."""
        await admin(db_session, client, sign_in)
        source = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Before"
        )
        mover = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, source, mover)
        challenge = await make_challenge(db_session, initial_points=100)
        solve = await record_solve(db_session, mover, challenge, team=source)
        destination = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="After"
        )

        await client.post(
            f"/api/admin/parties/members/{mover.id}/move",
            json={"to_team_id": str(destination.id)},
        )

        await db_session.refresh(solve)
        assert solve.team_id_at_solve == source.id

    async def test_moving_into_the_same_party_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Same"
        )
        mover = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, mover)

        response = await client.post(
            f"/api/admin/parties/members/{mover.id}/move", json={"to_team_id": str(team.id)}
        )

        assert response.json()["error"]["code"] == "already_there"


class TestRenaming:
    async def test_a_case_only_collision_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The column is CITEXT, so "the bold" and "The Bold" are one name."""
        await admin(db_session, client, sign_in)
        await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="The Bold"
        )
        other = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Others"
        )

        response = await client.patch(f"/api/admin/parties/{other.id}", json={"name": "the bold"})

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "name_taken"

    async def test_it_renames(self, client: AsyncClient, db_session: AsyncSession, sign_in) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Old Name"
        )

        response = await client.patch(
            f"/api/admin/parties/{team.id}", json={"name": "New Name", "reason": "Asked to"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"


class TestCapacity:
    async def test_it_refuses_a_cap_above_the_ceiling(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An unbounded party is just "everyone" under a union-of-solves
        standing."""
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Greedy"
        )

        response = await client.patch(
            f"/api/admin/parties/{team.id}", json={"max_members": MAX_MEMBERS_CEILING + 1}
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "max_members_too_high"

    async def test_it_allows_the_ceiling_itself(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Big"
        )

        response = await client.patch(
            f"/api/admin/parties/{team.id}", json={"max_members": MAX_MEMBERS_CEILING}
        )

        assert response.status_code == 200

    async def test_it_refuses_a_cap_below_the_current_membership(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Crowded")
        for _ in range(3):
            await add_member(
                db_session, team, await make_user(db_session, status=UserStatus.ACTIVE)
            )

        response = await client.patch(f"/api/admin/parties/{team.id}", json={"max_members": 2})

        assert response.json()["error"]["code"] == "max_members_below_current"


class TestLeadership:
    async def test_an_admin_can_transfer_it_without_being_the_leader(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole point: the leader is the person who is not around."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Leaderless")
        successor = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, successor)

        response = await client.post(
            f"/api/admin/parties/{team.id}/leader", json={"user_id": str(successor.id)}
        )

        assert response.status_code == 200
        await db_session.refresh(team)
        assert team.leader_user_id == successor.id

    async def test_it_refuses_a_non_member(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Closed"
        )
        stranger = await make_user(db_session, status=UserStatus.ACTIVE)

        response = await client.post(
            f"/api/admin/parties/{team.id}/leader", json={"user_id": str(stranger.id)}
        )

        assert response.json()["error"]["code"] == "not_a_member"

    async def test_removing_the_leader_hands_leadership_on(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A party with no leader has nobody able to accept a join request."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Succession")
        successor = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, successor)

        await client.delete(f"/api/admin/parties/{team.id}/members/{leader.id}")

        await db_session.refresh(team)
        assert team.leader_user_id == successor.id


class TestDisband:
    async def test_it_soft_deletes_and_frees_the_members(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Doomed")
        member = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, member)

        response = await client.post(
            f"/api/admin/parties/{team.id}/disband", json={"reason": "Asked to"}
        )

        assert response.status_code == 200
        await db_session.refresh(team)
        assert team.disbanded_at is not None
        assert await membership_for(db_session, member.id) is None
        # Still resolvable: the audit trail refers to it.
        assert await db_session.get(Team, team.id) is not None

    async def test_solves_survive_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Gone")
        challenge = await make_challenge(db_session, initial_points=100)
        solve = await record_solve(db_session, leader, challenge, team=team)

        await client.post(f"/api/admin/parties/{team.id}/disband", json={})

        await db_session.refresh(solve)
        assert solve.id is not None

    async def test_disbanding_twice_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Once"
        )
        await client.post(f"/api/admin/parties/{team.id}/disband", json={})

        response = await client.post(f"/api/admin/parties/{team.id}/disband", json={})

        assert response.json()["error"]["code"] == "already_disbanded"


class TestJoinRequests:
    async def test_an_admin_can_accept_a_stranded_request(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A leader who has gone home leaves these stuck, and unsticking them is
        the most likely reason to open a party at all."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Stranded")
        hopeful = await make_user(db_session, status=UserStatus.ACTIVE)
        request_row = TeamJoinRequest(team_id=team.id, user_id=hopeful.id)
        db_session.add(request_row)
        await db_session.flush()

        response = await client.post(
            f"/api/admin/parties/{team.id}/join-requests/{request_row.id}/accept"
        )

        assert response.status_code == 200
        await db_session.refresh(request_row)
        assert request_row.status == JoinRequestStatus.ACCEPTED
        assert (await membership_for(db_session, hopeful.id)) is not None

    async def test_accepting_into_a_full_party_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An override should not push a party past its cap; the player-facing
        code would then refuse to reason about it."""
        await admin(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Packed", max_members=1)
        hopeful = await make_user(db_session, status=UserStatus.ACTIVE)
        request_row = TeamJoinRequest(team_id=team.id, user_id=hopeful.id)
        db_session.add(request_row)
        await db_session.flush()

        response = await client.post(
            f"/api/admin/parties/{team.id}/join-requests/{request_row.id}/accept"
        )

        assert response.json()["error"]["code"] == "party_full"


class TestListing:
    async def test_it_flags_a_party_whose_leader_has_gone_quiet(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        absent = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, absent, name="Adrift")

        rows = (await client.get("/api/admin/parties")).json()
        row = next(r for r in rows if r["name"] == "Adrift")

        # Never logged in, so absent.
        assert row["leader_absent"] is True

    async def test_disbanded_parties_are_hidden_by_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        team = await make_team(
            db_session, await make_user(db_session, status=UserStatus.ACTIVE), name="Ghost Party"
        )
        await client.post(f"/api/admin/parties/{team.id}/disband", json={})

        hidden = (await client.get("/api/admin/parties")).json()
        shown = (await client.get("/api/admin/parties?include_disbanded=true")).json()

        assert all(r["name"] != "Ghost Party" for r in hidden)
        assert any(r["name"] == "Ghost Party" for r in shown)


class TestAccess:
    async def test_a_player_cannot_reach_any_of_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/parties")).status_code == 403

    async def test_an_organizer_cannot_either(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Every route here changes state, so they are Admin, not Staff."""
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        assert (await client.get("/api/admin/parties")).status_code == 403
