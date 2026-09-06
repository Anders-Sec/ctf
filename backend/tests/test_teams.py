"""Party creation, joining, leadership and removal (spec 002)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.team import (
    JoinRequestStatus,
    MembershipRole,
    RemovalReason,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamVisibility,
)
from app.models.user import UserStatus
from app.services import teams as team_service
from app.services.security import hash_password
from tests.factories import add_member, make_team, make_user


async def signed_in_player(db_session, client, sign_in, **kwargs):
    user = await make_user(db_session, status=kwargs.pop("status", UserStatus.ACTIVE), **kwargs)
    await sign_in(client, user)
    return user


class TestCreateParty:
    async def test_the_creator_becomes_the_leader(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await signed_in_player(db_session, client, sign_in)

        response = await client.post("/api/teams", json={"name": "The Mimics"})

        assert response.status_code == 201
        body = response.json()
        assert body["leader_user_id"] == str(user.id)
        assert body["members"][0]["is_leader"] is True
        assert body["max_members"] == 8

    async def test_a_pending_guest_may_create_a_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Only gameplay waits on approval, so a party can be formed early."""
        await signed_in_player(db_session, client, sign_in, status=UserStatus.PENDING_APPROVAL)

        response = await client.post("/api/teams", json={"name": "Early Birds"})

        assert response.status_code == 201

    async def test_a_disabled_user_may_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in_player(db_session, client, sign_in, status=UserStatus.DISABLED)

        response = await client.post("/api/teams", json={"name": "Banned Party"})

        assert response.status_code == 403

    async def test_names_are_unique_case_insensitively(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        await make_team(db_session, leader, name="Mimics")
        await signed_in_player(db_session, client, sign_in)

        response = await client.post("/api/teams", json={"name": "mimics"})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "team_name_unavailable"

    async def test_staff_impersonating_names_are_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in_player(db_session, client, sign_in)

        response = await client.post("/api/teams", json={"name": "CTF Admin Team"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_team_name"

    async def test_you_cannot_create_a_second_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await signed_in_player(db_session, client, sign_in)
        await make_team(db_session, user)

        response = await client.post("/api/teams", json={"name": "Second Party"})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_in_party"

    async def test_a_private_party_password_is_never_returned(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(
            "/api/teams",
            json={"name": "Secret Cabal", "visibility": "private", "join_password": "hunter2"},
        )

        assert response.status_code == 201
        assert "hunter2" not in response.text
        assert response.json()["requires_password"] is True


class TestJoining:
    async def test_anyone_may_join_a_public_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(db_session, await make_user(db_session))
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(f"/api/teams/{team.id}/join", json={})

        assert response.status_code == 200
        assert response.json()["member_count"] == 2

    async def test_a_private_party_needs_the_password(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(
            db_session,
            await make_user(db_session),
            visibility=TeamVisibility.PRIVATE,
            join_password_hash=hash_password("hunter2"),
        )
        await signed_in_player(db_session, client, sign_in)

        wrong = await client.post(f"/api/teams/{team.id}/join", json={"password": "nope"})
        right = await client.post(f"/api/teams/{team.id}/join", json={"password": "hunter2"})

        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "invalid_party_password"
        assert right.status_code == 200

    async def test_a_private_party_without_a_password_requires_a_request(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(
            db_session, await make_user(db_session), visibility=TeamVisibility.PRIVATE
        )
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(f"/api/teams/{team.id}/join", json={})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "join_request_required"

    async def test_a_full_party_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Eight is the cap, and the ninth adventurer waits outside."""
        leader = await make_user(db_session)
        team = await make_team(db_session, leader)
        for _ in range(7):
            await add_member(db_session, team, await make_user(db_session))
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(f"/api/teams/{team.id}/join", json={})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "team_full"

    async def test_joining_a_second_party_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await signed_in_player(db_session, client, sign_in)
        await make_team(db_session, user)
        other = await make_team(db_session, await make_user(db_session))

        response = await client.post(f"/api/teams/{other.id}/join", json={})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_in_party"

    async def test_a_disbanded_party_cannot_be_joined(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from datetime import UTC, datetime

        team = await make_team(db_session, await make_user(db_session))
        team.disbanded_at = datetime.now(UTC)
        await db_session.flush()
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(f"/api/teams/{team.id}/join", json={})

        assert response.status_code == 404


class TestLeavingAndKicking:
    async def test_a_member_can_leave(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(db_session, await make_user(db_session))
        user = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, user)

        response = await client.delete(f"/api/teams/{team.id}/members/{user.id}")

        assert response.status_code == 200
        assert await team_service.active_membership_for(db_session, user.id) is None

    async def test_leaving_keeps_the_history_row(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Anti-cheat review (spec 007) needs to see who was where and when."""
        team = await make_team(db_session, await make_user(db_session))
        user = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, user)

        await client.delete(f"/api/teams/{team.id}/members/{user.id}")

        rows = (
            (
                await db_session.execute(
                    select(TeamMembership).where(TeamMembership.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].removal_reason == RemovalReason.LEFT

    async def test_a_leaver_may_join_another_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Rosters stay open, which is safe because scores are personal."""
        first = await make_team(db_session, await make_user(db_session))
        second = await make_team(db_session, await make_user(db_session))
        user = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, first, user)

        await client.delete(f"/api/teams/{first.id}/members/{user.id}")
        response = await client.post(f"/api/teams/{second.id}/join", json={})

        assert response.status_code == 200

    async def test_the_leader_can_kick_a_member(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        victim = await make_user(db_session)
        await add_member(db_session, team, victim)

        response = await client.delete(f"/api/teams/{team.id}/members/{victim.id}")

        assert response.status_code == 200
        assert await team_service.active_membership_for(db_session, victim.id) is None

    async def test_a_member_cannot_kick_anyone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader)
        member = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, member)
        other = await make_user(db_session)
        await add_member(db_session, team, other)

        response = await client.delete(f"/api/teams/{team.id}/members/{other.id}")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "not_party_leader"

    async def test_a_leader_cannot_kick_themselves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Leaving is the supported route, and it hands leadership on properly."""
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        await add_member(db_session, team, await make_user(db_session))

        # Self-removal goes down the leave path, which is allowed and transfers.
        response = await client.delete(f"/api/teams/{team.id}/members/{leader.id}")

        assert response.status_code == 200
        await db_session.refresh(team)
        assert team.leader_user_id != leader.id

    async def test_kicks_are_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        victim = await make_user(db_session)
        await add_member(db_session, team, victim)

        await client.delete(f"/api/teams/{team.id}/members/{victim.id}")

        entry = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "team.kick", AuditLog.target_id == team.id
                )
            )
        ).scalar_one()
        assert entry.actor_user_id == leader.id
        assert entry.meta["user_id"] == str(victim.id)
        # The request id ties the action back to the server logs.
        assert entry.request_id is not None


class TestLeadership:
    async def test_leadership_passes_to_the_longest_tenured_member(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A party with no leader could not admit or remove anyone."""
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        first_joiner = await make_user(db_session)
        await add_member(db_session, team, first_joiner)
        await add_member(db_session, team, await make_user(db_session))

        await client.delete(f"/api/teams/{team.id}/members/{leader.id}")

        await db_session.refresh(team)
        assert team.leader_user_id == first_joiner.id

    async def test_the_last_member_leaving_disbands_the_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)

        await client.delete(f"/api/teams/{team.id}/members/{leader.id}")

        await db_session.refresh(team)
        assert team.disbanded_at is not None

    async def test_a_disbanded_party_is_not_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Its audit trail must remain resolvable."""
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        team_id = team.id

        await client.delete(f"/api/teams/{team.id}/members/{leader.id}")

        assert await db_session.get(Team, team_id) is not None

    async def test_the_leader_can_transfer_leadership(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        successor = await make_user(db_session)
        await add_member(db_session, team, successor)

        response = await client.post(
            f"/api/teams/{team.id}/leader", json={"user_id": str(successor.id)}
        )

        assert response.status_code == 200
        await db_session.refresh(team)
        assert team.leader_user_id == successor.id

        roles = {m.user_id: m.role for m in await team_service.load_members(db_session, team.id)}
        assert roles[successor.id] == MembershipRole.LEADER
        assert roles[leader.id] == MembershipRole.MEMBER

    async def test_leadership_cannot_be_given_to_an_outsider(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader)
        stranger = await make_user(db_session)

        response = await client.post(
            f"/api/teams/{team.id}/leader", json={"user_id": str(stranger.id)}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "not_in_party"

    async def test_a_member_cannot_seize_leadership(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader)
        member = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, member)

        response = await client.post(
            f"/api/teams/{team.id}/leader", json={"user_id": str(member.id)}
        )

        assert response.status_code == 403


class TestJoinRequests:
    async def test_a_request_can_be_made_and_accepted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        applicant = await signed_in_player(db_session, client, sign_in)

        created = await client.post(
            f"/api/teams/{team.id}/join-requests", json={"message": "Let me in"}
        )
        assert created.status_code == 201
        request_id = created.json()["id"]

        await sign_in(client, leader)
        accepted = await client.post(f"/api/teams/{team.id}/join-requests/{request_id}/accept")

        assert accepted.status_code == 200
        membership = await team_service.active_membership_for(db_session, applicant.id)
        assert membership is not None and membership.team_id == team.id

    async def test_a_request_can_be_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        applicant = await signed_in_player(db_session, client, sign_in)
        created = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        await sign_in(client, leader)
        response = await client.post(
            f"/api/teams/{team.id}/join-requests/{created.json()['id']}/reject"
        )

        assert response.status_code == 200
        assert await team_service.active_membership_for(db_session, applicant.id) is None

    async def test_only_the_leader_sees_pending_requests(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        member = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, member)

        response = await client.get(f"/api/teams/{team.id}/join-requests")

        assert response.status_code == 403

    async def test_requesting_twice_returns_the_same_request(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(
            db_session, await make_user(db_session), visibility=TeamVisibility.PRIVATE
        )
        await signed_in_player(db_session, client, sign_in)

        first = await client.post(f"/api/teams/{team.id}/join-requests", json={})
        second = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        assert first.json()["id"] == second.json()["id"]

    async def test_capacity_is_rechecked_at_accept_time(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The party may have filled up while the request sat waiting."""
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        applicant = await signed_in_player(db_session, client, sign_in)
        created = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        for _ in range(7):
            await add_member(db_session, team, await make_user(db_session))

        await sign_in(client, leader)
        response = await client.post(
            f"/api/teams/{team.id}/join-requests/{created.json()['id']}/accept"
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "team_full"
        assert await team_service.active_membership_for(db_session, applicant.id) is None

    async def test_an_applicant_who_joined_elsewhere_is_not_added_twice(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        applicant = await signed_in_player(db_session, client, sign_in)
        created = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        elsewhere = await make_team(db_session, await make_user(db_session))
        await add_member(db_session, elsewhere, applicant)

        await sign_in(client, leader)
        response = await client.post(
            f"/api/teams/{team.id}/join-requests/{created.json()['id']}/accept"
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "applicant_in_other_party"

    async def test_a_decided_request_cannot_be_decided_again(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)
        await signed_in_player(db_session, client, sign_in)
        created = await client.post(f"/api/teams/{team.id}/join-requests", json={})
        request_id = created.json()["id"]

        await sign_in(client, leader)
        await client.post(f"/api/teams/{team.id}/join-requests/{request_id}/reject")
        again = await client.post(f"/api/teams/{team.id}/join-requests/{request_id}/accept")

        assert again.status_code == 409
        assert again.json()["error"]["code"] == "request_decided"

    async def test_an_applicant_can_withdraw(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(
            db_session, await make_user(db_session), visibility=TeamVisibility.PRIVATE
        )
        await signed_in_player(db_session, client, sign_in)
        created = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        response = await client.delete(f"/api/teams/{team.id}/join-requests/{created.json()['id']}")

        assert response.status_code == 200
        row = await db_session.get(TeamJoinRequest, uuid.UUID(created.json()["id"]))
        assert row is not None and row.status == JoinRequestStatus.CANCELLED

    async def test_public_parties_do_not_take_requests(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(db_session, await make_user(db_session))
        await signed_in_player(db_session, client, sign_in)

        response = await client.post(f"/api/teams/{team.id}/join-requests", json={})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "team_is_public"


class TestPartySettings:
    async def test_the_leader_can_rename_the_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader, name="Old Name")

        response = await client.patch(f"/api/teams/{team.id}", json={"name": "New Name"})

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_a_member_cannot_change_settings(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        team = await make_team(db_session, await make_user(db_session))
        member = await signed_in_player(db_session, client, sign_in)
        await add_member(db_session, team, member)

        response = await client.patch(f"/api/teams/{team.id}", json={"name": "Hijacked"})

        assert response.status_code == 403

    async def test_going_public_clears_the_password(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A stale hash would silently resurrect on a switch back to private."""
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(
            db_session,
            leader,
            visibility=TeamVisibility.PRIVATE,
            join_password_hash=hash_password("hunter2"),
        )

        await client.patch(f"/api/teams/{team.id}", json={"visibility": "public"})

        await db_session.refresh(team)
        assert team.join_password_hash is None

    async def test_a_weak_password_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await signed_in_player(db_session, client, sign_in)
        team = await make_team(db_session, leader, visibility=TeamVisibility.PRIVATE)

        response = await client.patch(f"/api/teams/{team.id}", json={"join_password": "abc"})

        assert response.status_code == 422


class TestPartyListing:
    async def test_private_parties_are_hidden_from_the_browser(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await make_team(db_session, await make_user(db_session), name="Open Door")
        await make_team(
            db_session,
            await make_user(db_session),
            name="Hidden Cabal",
            visibility=TeamVisibility.PRIVATE,
        )
        await signed_in_player(db_session, client, sign_in)

        names = {row["name"] for row in (await client.get("/api/teams")).json()}

        assert "Open Door" in names
        assert "Hidden Cabal" not in names

    async def test_you_can_always_see_your_own_private_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await signed_in_player(db_session, client, sign_in)
        await make_team(db_session, user, name="My Cabal", visibility=TeamVisibility.PRIVATE)

        names = {row["name"] for row in (await client.get("/api/teams")).json()}

        assert "My Cabal" in names

    async def test_the_listing_reports_space(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Nearly Full")
        for _ in range(7):
            await add_member(db_session, team, await make_user(db_session))
        await signed_in_player(db_session, client, sign_in)

        row = next(r for r in (await client.get("/api/teams")).json() if r["name"] == "Nearly Full")

        assert row["member_count"] == 8
        assert row["has_space"] is False

    async def test_disbanded_parties_are_not_listed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from datetime import UTC, datetime

        team = await make_team(db_session, await make_user(db_session), name="Gone")
        team.disbanded_at = datetime.now(UTC)
        await db_session.flush()
        await signed_in_player(db_session, client, sign_in)

        names = {row["name"] for row in (await client.get("/api/teams")).json()}

        assert "Gone" not in names


class TestNameValidation:
    @pytest.mark.parametrize("name", ["ab", "x" * 33, "  ", "admin squad"])
    def test_bad_names_are_refused(self, name: str) -> None:
        with pytest.raises(team_service.InvalidName):
            team_service.validate_name(name)

    def test_whitespace_is_collapsed(self) -> None:
        assert team_service.validate_name("  The   Mimics  ") == "The Mimics"
