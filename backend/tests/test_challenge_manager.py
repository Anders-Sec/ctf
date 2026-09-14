"""The admin challenge manager: counts, filters, search, zones (spec 041)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    BossTier,
    ChallengeState,
    Difficulty,
    MatchType,
    points_for,
)
from app.models.hint import Hint
from app.models.skill import ChallengeSkill, Skill
from app.models.user import UserRole, UserStatus
from app.services import challenge_manager
from tests.factories import make_category, make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestCounts:
    async def test_answer_count_is_real(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The regression this spec exists partly to fix.

        It was ``len(c.answers) if "answers" in c.__dict__ else 0`` against a
        ``lazy="raise"`` relationship that was never eager-loaded — so it was
        **always zero**, for every challenge, since the listing shipped. Nothing
        rendered it, so nothing noticed.
        """
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)
        await make_challenge(
            db_session,
            category=category,
            title="Three Flags",
            answers=[
                (MatchType.EXACT, "one"),
                (MatchType.EXACT, "two"),
                (MatchType.EXACT, "three"),
            ],
        )
        await make_challenge(db_session, category=category, title="No Flags", answers=[])

        rows = {r["title"]: r for r in (await client.get("/api/admin/challenges")).json()}

        assert rows["Three Flags"]["answer_count"] == 3
        assert rows["No Flags"]["answer_count"] == 0

    async def test_hint_and_skill_counts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Well Equipped")
        skill = Skill(name=f"Skill {challenge.id.hex[:8]}", category_id=category.id)
        db_session.add(skill)
        await db_session.flush()
        db_session.add(Hint(challenge_id=challenge.id, title="A", body="b", cost=10))
        db_session.add(Hint(challenge_id=challenge.id, title="B", body="b", cost=20))
        db_session.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill.id))
        await db_session.flush()

        row = next(
            r
            for r in (await client.get("/api/admin/challenges")).json()
            if r["title"] == "Well Equipped"
        )

        assert row["hint_count"] == 2
        assert row["skill_count"] == 1

    async def test_counts_do_not_scale_with_rows(self, db_session: AsyncSession) -> None:
        """Four aggregates, not four per challenge — the N+1 that only shows up
        at 242 and never in a test with three."""
        category = await make_category(db_session)
        for index in range(6):
            await make_challenge(db_session, category=category, title=f"Row {index}")
        await db_session.flush()

        statements: list[str] = []
        engine = db_session.bind.sync_engine

        def record(conn, cursor, statement, parameters, context, executemany) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            found, _ = await challenge_manager.list_challenges(
                db_session, challenge_manager.ChallengeFilters()
            )
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(found) >= 6
        # One for the challenges, one for the eager-loaded categories, four
        # aggregates. Six rows would make a per-row implementation 24+.
        assert len(statements) <= 8, statements


class TestFilters:
    async def test_no_flag_finds_only_the_unsolvable(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        await make_challenge(
            db_session, category=category, title="Solvable", answers=[(MatchType.EXACT, "x")]
        )
        await make_challenge(db_session, category=category, title="Unsolvable", answers=[])

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.NO_FLAG),
        )

        assert [c.title for c in found] == ["Unsolvable"]

    async def test_no_description_treats_whitespace_as_empty(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        await make_challenge(db_session, category=category, title="Written", body="A body.")
        await make_challenge(db_session, category=category, title="Blank", body="   ")

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.NO_DESCRIPTION),
        )

        assert [c.title for c in found] == ["Blank"]

    async def test_no_skills_finds_xp_that_lands_nowhere(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        mapped = await make_challenge(db_session, category=category, title="Mapped")
        await make_challenge(db_session, category=category, title="Unmapped")
        skill = Skill(name="A Real Skill", category_id=category.id)
        db_session.add(skill)
        await db_session.flush()
        db_session.add(ChallengeSkill(challenge_id=mapped.id, skill_id=skill.id))
        await db_session.flush()

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.NO_SKILLS),
        )

        titles = {c.title for c in found}
        assert "Unmapped" in titles
        assert "Mapped" not in titles

    async def test_no_hints(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        hinted = await make_challenge(db_session, category=category, title="Hinted")
        await make_challenge(db_session, category=category, title="Hintless")
        db_session.add(Hint(challenge_id=hinted.id, title="A", body="b", cost=0))
        await db_session.flush()

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.NO_HINTS),
        )

        titles = {c.title for c in found}
        assert "Hintless" in titles
        assert "Hinted" not in titles

    async def test_draft_is_the_prelaunch_checklist(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        await make_challenge(
            db_session, category=category, title="Ready", state=ChallengeState.PUBLISHED
        )
        await make_challenge(
            db_session, category=category, title="Unfinished", state=ChallengeState.DRAFT
        )

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.DRAFT),
        )

        titles = {c.title for c in found}
        assert "Unfinished" in titles
        assert "Ready" not in titles

    async def test_zone_has_no_boss_names_the_candidates(self, db_session: AsyncSession) -> None:
        """It returns the challenges *in* a bossless zone, not the zone — so the
        result is something you can act on."""
        bossed = await make_category(db_session, name="Bossed Zone")
        bossless = await make_category(db_session, name="Bossless Zone")
        boss = await make_challenge(db_session, category=bossed, title="The Boss")
        boss.boss_tier = BossTier.CITY
        await make_challenge(db_session, category=bossed, title="Sidekick")
        await make_challenge(db_session, category=bossless, title="Leaderless")
        await db_session.flush()

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(problem=challenge_manager.Problem.ZONE_HAS_NO_BOSS),
        )

        titles = {c.title for c in found}
        assert "Leaderless" in titles
        assert "The Boss" not in titles
        assert "Sidekick" not in titles

    async def test_xp_differs_from_difficulty(self, db_session: AsyncSession, settings) -> None:
        category = await make_category(db_session)
        await make_challenge(
            db_session,
            category=category,
            title="On The Ladder",
            difficulty=Difficulty.HARD,
            initial_points=points_for(Difficulty.HARD, settings.xp_base),
        )
        await make_challenge(
            db_session,
            category=category,
            title="Retuned",
            difficulty=Difficulty.HARD,
            initial_points=345,
        )

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(
                problem=challenge_manager.Problem.XP_DIFFERS_FROM_DIFFICULTY
            ),
        )

        assert [c.title for c in found] == ["Retuned"]

    async def test_search_matches_title_slug_and_body(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        await make_challenge(db_session, category=category, title="Pigeon Post", body="Nothing.")
        await make_challenge(db_session, category=category, title="Elsewhere", body="A pigeon.")
        await make_challenge(db_session, category=category, title="Unrelated", body="Nothing.")

        found, _ = await challenge_manager.list_challenges(
            db_session, challenge_manager.ChallengeFilters(search="pigeon")
        )

        assert {c.title for c in found} == {"Pigeon Post", "Elsewhere"}

    async def test_search_does_not_match_a_flag(self, db_session: AsyncSession) -> None:
        """A search box that matches answers is a search box that puts them on
        screen. An admin hunting for a flag has the drawer."""
        category = await make_category(db_session)
        await make_challenge(
            db_session,
            category=category,
            title="Secretive",
            body="Nothing here.",
            answers=[(MatchType.EXACT, "supersecretvalue")],
        )

        found, _ = await challenge_manager.list_challenges(
            db_session, challenge_manager.ChallengeFilters(search="supersecretvalue")
        )

        assert found == []

    async def test_filters_combine(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        await make_challenge(
            db_session,
            category=category,
            title="Draft Hard",
            difficulty=Difficulty.HARD,
            state=ChallengeState.DRAFT,
        )
        await make_challenge(
            db_session,
            category=category,
            title="Live Hard",
            difficulty=Difficulty.HARD,
            state=ChallengeState.PUBLISHED,
        )
        await make_challenge(
            db_session,
            category=category,
            title="Draft Easy",
            difficulty=Difficulty.EASY,
            state=ChallengeState.DRAFT,
        )

        found, _ = await challenge_manager.list_challenges(
            db_session,
            challenge_manager.ChallengeFilters(
                difficulty=Difficulty.HARD, state=ChallengeState.DRAFT
            ),
        )

        assert [c.title for c in found] == ["Draft Hard"]


class TestZoneSummaries:
    async def test_a_zone_reports_its_xp_boss_and_drafts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session, name="Zone Under Test")
        await make_challenge(
            db_session,
            category=category,
            title="One",
            initial_points=200,
            state=ChallengeState.DRAFT,
        )
        boss = await make_challenge(
            db_session,
            category=category,
            title="Two",
            initial_points=300,
            state=ChallengeState.PUBLISHED,
        )
        boss.boss_tier = BossTier.BOROUGH
        await db_session.flush()

        zones = {z["name"]: z for z in (await client.get("/api/admin/zones")).json()}

        assert zones["Zone Under Test"]["challenge_count"] == 2
        assert zones["Zone Under Test"]["total_xp"] == 500
        assert zones["Zone Under Test"]["boss_challenge_id"] == str(boss.id)
        assert zones["Zone Under Test"]["boss_tier"] == "borough"
        assert zones["Zone Under Test"]["draft_count"] == 1
        assert zones["Zone Under Test"]["published_count"] == 1

    async def test_a_zone_with_no_boss_reports_none(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session, name="Leaderless Zone")
        await make_challenge(db_session, category=category, title="Alone")

        zones = {z["name"]: z for z in (await client.get("/api/admin/zones")).json()}

        assert zones["Leaderless Zone"]["boss_challenge_id"] is None
        assert zones["Leaderless Zone"]["boss_tier"] is None

    async def test_zones_come_back_in_display_order(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The dungeon's order, not the alphabet's."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await make_category(db_session, name="Aardvark", display_order=99)
        await make_category(db_session, name="Zebra", display_order=1)

        names = [z["name"] for z in (await client.get("/api/admin/zones")).json()]

        assert names.index("Zebra") < names.index("Aardvark")


class TestAccess:
    async def test_a_player_may_not_list(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/challenges")).status_code == 403
        assert (await client.get("/api/admin/zones")).status_code == 403
