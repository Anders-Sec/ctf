"""The staff board and the audit log's filters (spec 051)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_challenge, make_team, make_user, record_solve


async def staff(db_session: AsyncSession, client: AsyncClient, sign_in, role=UserRole.ADMIN):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def seeded(settings: Settings) -> None:
    """Solves written straight to the database bypass the paths that invalidate
    the board, so say so explicitly — the same call a real solve makes."""
    await scoreboard_cache.mark_dirty(get_redis(settings))


class TestTheSplit:
    async def test_solve_and_adjustment_points_add_back_to_the_total(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """One number, two surfaces. If these drift the page is worse than
        useless, because it is consulted precisely to settle a dispute."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Rin")
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)

        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 25, "reason": "Broken challenge"},
        )

        body = (await client.get("/api/admin/scoreboard")).json()
        row = next(r for r in body["players"] if r["display_name"] == "Rin")

        assert row["adjustment_points"] == 25
        assert row["solve_points"] + row["adjustment_points"] == row["score"]

    async def test_a_player_with_no_adjustment_is_all_solve_points(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Vex")
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)
        await seeded(settings)

        body = (await client.get("/api/admin/scoreboard")).json()
        row = next(r for r in body["players"] if r["display_name"] == "Vex")

        assert row["adjustment_points"] == 0
        assert row["solve_points"] == row["score"]

    async def test_a_party_carries_its_members_adjustments_as_well_as_its_own(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The rule the public board totals under — a member's personal points
        are part of their party — so the split has to follow it or the halves
        will not add up."""
        await staff(db_session, client, sign_in)
        leader = await make_user(db_session, display_name="Bell")
        team = await make_team(db_session, leader, name="The Bold")
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, leader, challenge)

        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(leader.id), "points": 10, "reason": "Personal"},
        )
        await client.post(
            "/api/admin/adjustments",
            json={"team_id": str(team.id), "points": 5, "reason": "Party"},
        )

        body = (await client.get("/api/admin/scoreboard")).json()
        row = next(r for r in body["teams"] if r["name"] == "The Bold")

        assert row["adjustment_points"] == 15
        assert row["solve_points"] + row["adjustment_points"] == row["score"]


class TestTieBreaks:
    async def test_equal_scores_are_ordered_by_who_got_there_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, initial_points=100)
        early = await make_user(db_session, display_name="Early")
        late = await make_user(db_session, display_name="Late")
        now = datetime.now(UTC)
        await record_solve(db_session, early, challenge, submitted_at=now - timedelta(hours=2))
        await record_solve(db_session, late, challenge, submitted_at=now)
        await seeded(settings)

        body = (await client.get("/api/admin/scoreboard")).json()
        names = [
            r["display_name"] for r in body["players"] if r["display_name"] in {"Early", "Late"}
        ]

        assert names == ["Early", "Late"]

    async def test_the_timestamp_that_decided_it_is_visible(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """Otherwise the page asks an admin to trust the sort, which is the one
        thing they came here not to do."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Rin")
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)
        await seeded(settings)

        body = (await client.get("/api/admin/scoreboard")).json()
        row = next(r for r in body["players"] if r["display_name"] == "Rin")

        assert row["last_gain_at"] is not None


class TestUnranked:
    async def test_a_disabled_player_who_scored_is_listed_but_not_ranked(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """They vanish from the public board and everyone below moves up. An
        admin settling a placement needs to see that happened."""
        await staff(db_session, client, sign_in)
        gone = await make_user(db_session, display_name="Ghost", status=UserStatus.DISABLED)
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, gone, challenge)
        await seeded(settings)

        body = (await client.get("/api/admin/scoreboard")).json()

        assert all(r["display_name"] != "Ghost" for r in body["players"])
        unranked = next(r for r in body["unranked"] if r["display_name"] == "Ghost")
        assert unranked["reason"] == "disabled"
        assert unranked["score"] > 0

    async def test_an_account_that_never_played_is_not_listed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Every staff account and every pending signup would bury the one
        disabled player this section exists for."""
        await staff(db_session, client, sign_in)
        await make_user(db_session, display_name="Never", status=UserStatus.DISABLED)

        body = (await client.get("/api/admin/scoreboard")).json()

        assert all(r["display_name"] != "Never" for r in body["unranked"])

    async def test_ranks_match_the_public_board_exactly(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """The reason unranked accounts are a separate list: weaving them into
        the ranking would make this board disagree with the public one about
        every position below them."""
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, initial_points=100)
        for name in ("A", "B", "C"):
            player = await make_user(db_session, display_name=name)
            await record_solve(db_session, player, challenge)
        disabled = await make_user(db_session, display_name="D", status=UserStatus.DISABLED)
        await record_solve(db_session, disabled, challenge)
        await seeded(settings)

        admin_body = (await client.get("/api/admin/scoreboard")).json()
        public = (await client.get("/api/scoreboard/players")).json()

        assert [r["rank"] for r in admin_body["players"]] == [r["rank"] for r in public["entries"]]
        assert [r["user_id"] for r in admin_body["players"]] == [
            r["user_id"] for r in public["entries"]
        ]


class TestAccess:
    async def test_staff_may_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in, role=UserRole.ORGANIZER)

        assert (await client.get("/api/admin/scoreboard")).status_code == 200

    async def test_a_player_may_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/scoreboard")).status_code == 403

    async def test_it_is_readable_before_the_event_starts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """And after it ends, which is when placements are actually settled —
        exactly when the public board's gate would be shut."""
        await staff(db_session, client, sign_in)

        assert (await client.get("/api/admin/scoreboard")).status_code == 200


class TestAuditFilters:
    """What spec 051 §2.1 added to an endpoint that only took `action`."""

    async def test_it_reports_the_total_matching_not_the_page(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        for index in range(3):
            await client.post(
                "/api/admin/adjustments",
                json={"user_id": str(player.id), "points": 1, "reason": f"Note {index}"},
            )

        body = (await client.get("/api/admin/audit-log?limit=1")).json()

        assert len(body["entries"]) == 1
        assert body["total"] >= 3

    async def test_it_filters_by_target_type(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 5, "reason": "Points"},
        )

        # An adjustment is recorded against the *subject* — the player or party
        # whose score moved — not against the adjustment row.
        body = (await client.get("/api/admin/audit-log?target_type=user")).json()

        assert body["entries"]
        assert all(row["target_type"] == "user" for row in body["entries"])

    async def test_it_filters_by_actor(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 5, "reason": "Points"},
        )

        body = (await client.get(f"/api/admin/audit-log?actor_user_id={admin.id}")).json()

        assert body["entries"]
        assert all(row["actor_user_id"] == str(admin.id) for row in body["entries"])

    async def test_it_searches_reason_text(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 5, "reason": "Compensating a flood"},
        )

        body = (await client.get("/api/admin/audit-log?search=flood")).json()

        assert any("flood" in (row["reason"] or "") for row in body["entries"])

    async def test_a_date_range_narrows_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 5, "reason": "Recent"},
        )

        # Passed as params, not interpolated: an ISO timestamp carries a "+"
        # that a raw query string would deliver as a space.
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        future = (await client.get("/api/admin/audit-log", params={"since": tomorrow})).json()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        recent = (await client.get("/api/admin/audit-log", params={"since": yesterday})).json()

        assert future["total"] == 0
        assert recent["total"] >= 1

    async def test_the_actions_endpoint_lists_only_what_is_present(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Read from the data rather than a hardcoded list, which would drift the
        first time a verb was added."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 5, "reason": "Points"},
        )

        actions = (await client.get("/api/admin/audit-log/actions")).json()

        assert "score.adjust" in actions
        assert "no.such.verb" not in actions

    async def test_a_player_cannot_read_the_actions(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/audit-log/actions")).status_code == 403
