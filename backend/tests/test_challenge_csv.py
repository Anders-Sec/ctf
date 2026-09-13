"""Challenge import and export as CSV (spec 026)."""

import csv
import io

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import Category, Challenge, ChallengeState, Difficulty, points_for
from app.models.user import UserRole, UserStatus
from app.services import challenge_csv
from tests.factories import make_category, make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


def rows_of(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def csv_of(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=challenge_csv.COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: "" for c in challenge_csv.COLUMNS} | row)
    return out.getvalue()


class TestTemplate:
    async def test_it_has_eleven_rows_for_every_category(self, db_session: AsyncSession) -> None:
        categories = (await db_session.execute(select(Category.name))).scalars().all()

        rows = rows_of(await challenge_csv.build_template(db_session))

        counted: dict[str, int] = {}
        for row in rows:
            counted[row["category"]] = counted.get(row["category"], 0) + 1
        assert set(counted) == set(categories)
        assert set(counted.values()) == {11}

    async def test_the_prefilled_spread_matches_the_xp_budget(
        self, db_session: AsyncSession
    ) -> None:
        """1,900 XP per category is not a coincidence — 018 budgeted ~2,000 per
        category and ~42,000 overall, so filling the template in as-is produces
        an event that already matches the curve levels were tuned against."""
        total = sum(points_for(d, 10) for d in challenge_csv.DEFAULT_LADDER)

        assert len(challenge_csv.DEFAULT_LADDER) == 11
        assert total == 1900

    async def test_intro_gets_a_gentler_ladder(self) -> None:
        # A nearly-impossible challenge in the zone that gates the whole dungeon
        # would be a wall at the front door.
        assert Difficulty.NEARLY_IMPOSSIBLE not in challenge_csv.INTRO_LADDER
        assert Difficulty.VERY_HARD not in challenge_csv.INTRO_LADDER
        assert len(challenge_csv.INTRO_LADDER) == 11

    async def test_it_leaves_the_authoring_columns_blank(self, db_session: AsyncSession) -> None:
        rows = rows_of(await challenge_csv.build_template(db_session))

        assert all(row["title"] == "" for row in rows)
        assert all(row["flag"] == "" for row in rows)
        assert all(row["difficulty"] for row in rows)


class TestImport:
    async def test_it_creates_challenges_with_derived_points(
        self, db_session: AsyncSession
    ) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of(
            [
                {
                    "category": category.name,
                    "title": "CSV First",
                    "difficulty": "medium",
                    "description": "Body.",
                    "flag": "flag{one}",
                }
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        assert report.ok
        assert report.created == 1
        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "CSV First"))
        ).scalar_one()
        # The CSV says how hard, never how many points.
        assert challenge.initial_points == points_for(Difficulty.MEDIUM, 10)

    async def test_new_challenges_land_as_drafts(self, db_session: AsyncSession) -> None:
        """242 challenges appearing live in one request is hard to undo."""
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of([{"category": category.name, "title": "CSV Draft", "difficulty": "easy"}])

        await challenge_csv.import_csv(db_session, text)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "CSV Draft"))
        ).scalar_one()
        assert challenge.state is ChallengeState.DRAFT

    async def test_a_single_bad_row_writes_nothing(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        before = (await db_session.execute(select(func.count(Challenge.id)))).scalar()
        text = csv_of(
            [
                {"category": category.name, "title": "CSV Good", "difficulty": "easy"},
                {"category": category.name, "title": "CSV Bad", "difficulty": "impossible"},
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        # A half-imported event is worse than a rejected one: you cannot tell
        # what landed without reading all 242 rows.
        assert not report.ok
        assert report.errors[0].row == 3
        assert report.errors[0].column == "difficulty"
        after = (await db_session.execute(select(func.count(Challenge.id)))).scalar()
        assert after == before

    async def test_a_dry_run_writes_nothing_but_reports_the_same(
        self, db_session: AsyncSession
    ) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        before = (await db_session.execute(select(func.count(Challenge.id)))).scalar()
        text = csv_of([{"category": category.name, "title": "CSV Dry", "difficulty": "hard"}])

        dry = await challenge_csv.import_csv(db_session, text, dry_run=True)
        after = (await db_session.execute(select(func.count(Challenge.id)))).scalar()
        real = await challenge_csv.import_csv(db_session, text)

        assert dry.created == real.created == 1
        assert after == before

    async def test_reimporting_updates_rather_than_duplicating(
        self, db_session: AsyncSession
    ) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        first = csv_of(
            [
                {
                    "category": category.name,
                    "title": "CSV Repeat",
                    "difficulty": "easy",
                    "description": "First.",
                }
            ]
        )
        second = csv_of(
            [
                {
                    "category": category.name,
                    "title": "CSV Repeat",
                    "difficulty": "hard",
                    "description": "Second.",
                }
            ]
        )

        await challenge_csv.import_csv(db_session, first)
        report = await challenge_csv.import_csv(db_session, second)

        # This is how a spreadsheet actually gets used: edit and re-upload.
        assert report.updated == 1
        assert report.created == 0
        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "CSV Repeat"))
        ).scalar_one()
        assert challenge.body == "Second."
        assert challenge.difficulty is Difficulty.HARD

    async def test_blank_rows_are_skipped(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of(
            [
                {"category": category.name, "difficulty": "easy"},
                {"category": category.name, "difficulty": "medium"},
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        # Untouched template rows are not mistakes.
        assert report.ok
        assert report.skipped == 2
        assert report.created == 0

    async def test_a_duplicate_title_in_the_file_is_refused(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of(
            [
                {"category": category.name, "title": "CSV Twice", "difficulty": "easy"},
                {"category": category.name, "title": "CSV Twice", "difficulty": "hard"},
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        # The second row would silently overwrite the first.
        assert not report.ok
        assert report.errors[0].column == "title"

    async def test_an_unknown_category_names_the_row(self, db_session: AsyncSession) -> None:
        text = csv_of([{"category": "Nowhere At All", "title": "CSV Lost", "difficulty": "easy"}])

        report = await challenge_csv.import_csv(db_session, text)

        assert not report.ok
        assert report.errors[0].column == "category"
        assert report.errors[0].row == 2

    async def test_an_unknown_skill_is_refused_not_skipped(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of(
            [
                {
                    "category": category.name,
                    "title": "CSV Skill",
                    "difficulty": "easy",
                    "skills": "No Such Skill",
                }
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        # A typo must not silently produce a challenge that feeds nothing.
        assert not report.ok
        assert report.errors[0].column == "skills"

    async def test_a_flag_containing_a_comma_survives(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        text = csv_of(
            [
                {
                    "category": category.name,
                    "title": "CSV Comma",
                    "difficulty": "easy",
                    "flag": 'flag{a,b,"c"}',
                }
            ]
        )

        report = await challenge_csv.import_csv(db_session, text)

        assert report.ok
        assert report.created == 1


class TestExport:
    async def test_export_round_trips(self, db_session: AsyncSession) -> None:
        category = (await db_session.execute(select(Category))).scalars().first()
        await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "CSV Round",
                        "difficulty": "medium",
                        "description": "Body.",
                        "flag": "flag{round}",
                    }
                ]
            ),
        )

        exported = await challenge_csv.build_export(db_session)
        report = await challenge_csv.import_csv(db_session, exported)

        # Export → import is a no-op, which is what makes import safe to try.
        assert report.ok
        assert report.created == 0


class TestAccess:
    async def test_a_player_may_not_export(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        response = await client.get("/api/admin/challenges/export.csv")

        assert response.status_code == 403

    async def test_an_admin_downloads_the_template(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.get("/api/admin/challenges/template.csv")

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]


class TestPointsOverride:
    """Spec 033: areas differ in size, and six ladder levels have to total what an
    eleven-challenge zone does. Without the column a re-import silently resets
    them to what difficulty derives."""

    async def test_points_override_difficulty(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,points,state,max_attempts,release_at,skills\n"
            f"{category.name},Very Easy,very_easy,,flag{{a_test_value}},100,,,,\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Very Easy"))
        ).scalar_one()
        assert challenge.initial_points == 100  # not difficulty x xp_base

    async def test_an_empty_points_cell_still_derives_from_difficulty(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,points,state,max_attempts,release_at,skills\n"
            f"{category.name},Derived,very_easy,,flag{{a_test_value}},,,,,\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Derived"))
        ).scalar_one()
        assert challenge.initial_points == points_for(Difficulty.VERY_EASY, settings.xp_base)

    async def test_a_negative_or_junk_points_cell_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,points,state,max_attempts,release_at,skills\n"
            f"{category.name},Bad,very_easy,,flag{{a_test_value}},nonsense,,,,\n"
        )

        report = await challenge_csv.import_csv(db_session, csv)

        assert any(e.column == "points" for e in report.errors)
        assert report.created == 0

    async def test_an_override_round_trips_through_export(
        self, db_session: AsyncSession
    ) -> None:
        """The point of the column: re-importing an export must not reset it."""
        category = await make_category(db_session)
        await make_challenge(
            db_session,
            category=category,
            title="Nearly Impossible",
            difficulty=Difficulty.NEARLY_IMPOSSIBLE,
            initial_points=900,
        )

        exported = await challenge_csv.build_export(db_session)
        await challenge_csv.import_csv(db_session, exported)

        challenge = (
            await db_session.execute(
                select(Challenge).where(Challenge.title == "Nearly Impossible")
            )
        ).scalar_one()
        assert challenge.initial_points == 900
