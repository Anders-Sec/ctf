"""Challenge import and export as CSV (specs 026, 040)."""

import csv
import io
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import (
    BossTier,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    DecayBasis,
    Difficulty,
    PreReleaseState,
    ScoringMode,
    UnlockRequirement,
    points_for,
)
from app.models.hint import Hint, HintUnlock
from app.models.user import UserRole, UserStatus
from app.services import answers as answer_service
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


class TestXpColumn:
    """XP is the file's number now (spec 040). Difficulty only fills a blank
    cell on a challenge that has no value yet."""

    async def test_xp_beats_difficulty(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,release_at,skills\n"
            f"{category.name},Very Easy,very_easy,,flag{{a_test_value}},100,,,,\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Very Easy"))
        ).scalar_one()
        assert challenge.initial_points == 100  # not difficulty x xp_base

    async def test_an_empty_xp_cell_falls_back_to_difficulty(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,release_at,skills\n"
            f"{category.name},Derived,very_easy,,flag{{a_test_value}},,,,,\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Derived"))
        ).scalar_one()
        assert challenge.initial_points == points_for(Difficulty.VERY_EASY, settings.xp_base)

    async def test_a_negative_or_junk_xp_cell_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,release_at,skills\n"
            f"{category.name},Bad,very_easy,,flag{{a_test_value}},nonsense,,,,\n"
        )

        report = await challenge_csv.import_csv(db_session, csv)

        assert any(e.column == "xp" for e in report.errors)
        assert report.created == 0

    async def test_an_override_round_trips_through_export(self, db_session: AsyncSession) -> None:
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


class TestLadderColumn:
    """Without it the System AI ladder cannot be authored from the spreadsheet at
    all, and its six challenges would need hand-editing after every import."""

    async def test_a_rung_round_trips(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,"
            "release_at,skills,ai_ladder_level\n"
            f"{category.name},Very Easy,very_easy,,flag{{a_test_value}},100,,,,,0\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Very Easy"))
        ).scalar_one()
        assert challenge.ai_ladder_level == 0
        assert f"{category.name},Very Easy" in await challenge_csv.build_export(db_session)

    async def test_two_rows_claiming_one_rung_are_refused(self, db_session: AsyncSession) -> None:
        """The partial unique index would catch it halfway through the apply;
        catching it here keeps the all-or-nothing promise."""
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,"
            "release_at,skills,ai_ladder_level\n"
            f"{category.name},First,very_easy,,flag{{one_test_value}},100,,,,,0\n"
            f"{category.name},Second,easy,,flag{{two_test_value}},150,,,,,0\n"
        )

        report = await challenge_csv.import_csv(db_session, csv)

        assert any(e.column == "ai_ladder_level" for e in report.errors)
        assert report.created == 0

    async def test_a_rung_outside_the_ladder_is_refused(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,"
            "release_at,skills,ai_ladder_level\n"
            f"{category.name},Too High,very_easy,,flag{{a_test_value}},100,,,,,9\n"
        )

        report = await challenge_csv.import_csv(db_session, csv)

        assert any(e.column == "ai_ladder_level" for e in report.errors)

    async def test_an_ordinary_row_stays_off_the_ladder(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        csv = (
            "category,title,difficulty,description,flag,xp,state,max_attempts,"
            "release_at,skills,ai_ladder_level\n"
            f"{category.name},Ordinary,very_easy,,flag{{a_test_value}},,,,,,\n"
        )

        await challenge_csv.import_csv(db_session, csv)

        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.title == "Ordinary"))
        ).scalar_one()
        assert challenge.ai_ladder_level is None


class TestFlagsColumn:
    """Spec 040: one flag and one match type was the narrow case. A challenge
    may accept several answers, and not all of them are plain strings."""

    async def test_a_json_array_becomes_several_answer_rules(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        flags = json.dumps(
            [
                "four four three",
                {"type": "exact", "value": "443"},
                {"type": "regex", "value": r"port\s*443", "options": {"ignore_case": True}},
                {"type": "numeric", "value": "443", "options": {"tolerance": 0}},
            ]
        )

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Ports",
                        "difficulty": "easy",
                        "flags": flags,
                    }
                ]
            ),
        )

        assert report.ok, report.errors
        challenge = await _challenge(db_session, "Ports")
        rules = await _answers(db_session, challenge)
        assert [r.match_type.value for r in rules] == [
            "case_insensitive",
            "exact",
            "regex",
            "numeric",
        ]
        # A bare string is the common case spelled short.
        assert rules[0].value == "four four three"
        assert rules[2].options == {"ignore_case": True}
        assert [r.display_order for r in rules] == [0, 1, 2, 3]

    async def test_any_of_the_rules_may_match(self, db_session: AsyncSession) -> None:
        """The reason for more than one flag in the first place."""
        category = await make_category(db_session)
        await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Loopback",
                        "difficulty": "easy",
                        "flags": json.dumps(["127.0.0.1", "localhost"]),
                    }
                ]
            ),
        )

        rules = await _answers(db_session, await _challenge(db_session, "Loopback"))
        assert answer_service.check("LOCALHOST", rules).correct
        assert answer_service.check("127.0.0.1", rules).correct
        assert not answer_service.check("0.0.0.0", rules).correct

    async def test_flag_and_flags_together_are_refused(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Both",
                        "difficulty": "easy",
                        "flag": "one",
                        "flags": json.dumps(["two"]),
                    }
                ]
            ),
        )

        assert any(e.column == "flags" for e in report.errors)
        assert report.created == 0

    async def test_a_pattern_that_will_not_compile_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        """Caught now, not at 09:00 on event day when a challenge silently
        refuses every correct answer."""
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Broken",
                        "difficulty": "easy",
                        "flags": json.dumps([{"type": "regex", "value": "(unclosed"}]),
                    }
                ]
            ),
        )

        assert any(e.column == "flags" and "[0]" in e.problem for e in report.errors)

    async def test_malformed_json_names_its_column(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Junk",
                        "difficulty": "easy",
                        "flags": "{not json",
                    }
                ]
            ),
        )

        assert any(e.column == "flags" for e in report.errors)

    async def test_editing_a_flag_keeps_the_answer_row(self, db_session: AsyncSession) -> None:
        """submission.matched_answer_id points at these rows, so a one-character
        fix must not blank the link across the whole submission log."""
        category = await make_category(db_session)
        rows = [
            {
                "category": category.name,
                "title": "Typo",
                "difficulty": "easy",
                "flags": json.dumps(["443"]),
            }
        ]
        await challenge_csv.import_csv(db_session, csv_of(rows))
        challenge = await _challenge(db_session, "Typo")
        before = (await _answers(db_session, challenge))[0].id

        rows[0]["flags"] = json.dumps(["444"])
        await challenge_csv.import_csv(db_session, csv_of(rows))

        after = await _answers(db_session, challenge)
        assert [r.id for r in after] == [before]
        assert after[0].value == "444"

    async def test_an_empty_array_clears_and_a_blank_cell_does_not(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        rows = [
            {
                "category": category.name,
                "title": "Clearing",
                "difficulty": "easy",
                "flags": json.dumps(["keep"]),
            }
        ]
        await challenge_csv.import_csv(db_session, csv_of(rows))
        challenge = await _challenge(db_session, "Clearing")

        # Blank is "not mentioned".
        rows[0]["flags"] = ""
        await challenge_csv.import_csv(db_session, csv_of(rows))
        assert len(await _answers(db_session, challenge)) == 1

        # An empty array is the explicit "clear this set".
        rows[0]["flags"] = "[]"
        await challenge_csv.import_csv(db_session, csv_of(rows))
        assert await _answers(db_session, challenge) == []


class TestHintsColumn:
    async def test_hints_import_with_costs_order_and_a_ladder(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        hints = json.dumps(
            [
                {"title": "Where to look", "body": "The headers.", "cost": 25},
                {"title": "The technique", "body": "Decode it.", "cost": 50, "requires": 0},
            ]
        )

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Hinted",
                        "difficulty": "medium",
                        "flag": "f",
                        "hints": hints,
                    }
                ]
            ),
        )

        assert report.ok, report.errors
        rows = await _hints(db_session, await _challenge(db_session, "Hinted"))
        assert [h.title for h in rows] == ["Where to look", "The technique"]
        assert [h.cost for h in rows] == [25, 50]
        assert [h.display_order for h in rows] == [0, 1]
        assert rows[1].prerequisite_hint_id == rows[0].id
        assert rows[0].prerequisite_hint_id is None

    async def test_a_forward_requires_is_refused(self, db_session: AsyncSession) -> None:
        """A hint gated on one further down the list can never unlock."""
        category = await make_category(db_session)
        hints = json.dumps(
            [
                {"title": "First", "body": "b", "requires": 1},
                {"title": "Second", "body": "b"},
            ]
        )

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Backwards",
                        "difficulty": "easy",
                        "hints": hints,
                    }
                ]
            ),
        )

        assert any(e.column == "hints" and "[0]" in e.problem for e in report.errors)

    async def test_dropping_a_bought_hint_is_refused(self, db_session: AsyncSession) -> None:
        """Someone paid for it. Deleting it here would erase the purchase, so the
        file is refused and the deletion stays a deliberate UI action."""
        category = await make_category(db_session)
        rows = [
            {
                "category": category.name,
                "title": "Paid",
                "difficulty": "medium",
                "hints": json.dumps([{"title": "Bought", "body": "b", "cost": 10}]),
            }
        ]
        await challenge_csv.import_csv(db_session, csv_of(rows))
        challenge = await _challenge(db_session, "Paid")
        hint = (await _hints(db_session, challenge))[0]

        buyer = await make_user(db_session, status=UserStatus.ACTIVE)
        db_session.add(
            HintUnlock(
                user_id=buyer.id,
                hint_id=hint.id,
                cost_charged=10,
                unlocked_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await db_session.flush()

        rows[0]["hints"] = "[]"
        report = await challenge_csv.import_csv(db_session, csv_of(rows))

        assert any(e.column == "hints" for e in report.errors)
        assert len(await _hints(db_session, challenge)) == 1

    async def test_an_unbought_hint_is_droppable(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        rows = [
            {
                "category": category.name,
                "title": "Free",
                "difficulty": "medium",
                "hints": json.dumps([{"title": "A", "body": "b"}, {"title": "B", "body": "b"}]),
            }
        ]
        await challenge_csv.import_csv(db_session, csv_of(rows))
        challenge = await _challenge(db_session, "Free")

        rows[0]["hints"] = json.dumps([{"title": "A", "body": "b"}])
        report = await challenge_csv.import_csv(db_session, csv_of(rows))

        assert report.ok, report.errors
        assert len(await _hints(db_session, challenge)) == 1


class TestUnlocksColumn:
    async def test_a_forward_reference_resolves(self, db_session: AsyncSession) -> None:
        """A generated file is ordered by category, so a prerequisite routinely
        sits further down the file than the challenge it gates."""
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Second Door",
                        "difficulty": "medium",
                        "unlocks": json.dumps(
                            [
                                {
                                    "type": "challenge_solved",
                                    "challenge": f"{category.name}/First Door",
                                }
                            ]
                        ),
                    },
                    {"category": category.name, "title": "First Door", "difficulty": "easy"},
                ]
            ),
        )

        assert report.ok, report.errors
        second = await _challenge(db_session, "Second Door")
        first = await _challenge(db_session, "First Door")
        requirements = await _unlocks(db_session, second)
        assert len(requirements) == 1
        assert requirements[0].required_challenge_id == first.id

    async def test_value_requirements_and_groups_import(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        unlocks = json.dumps(
            [
                {"type": "min_xp", "threshold": 500},
                {
                    "type": "percent_in_category",
                    "category": category.name,
                    "threshold": 50,
                    "group": 1,
                },
                {"type": "player_level", "threshold": 4, "group": 1},
            ]
        )

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Gated",
                        "difficulty": "hard",
                        "unlocks": unlocks,
                    }
                ]
            ),
        )

        assert report.ok, report.errors
        requirements = await _unlocks(db_session, await _challenge(db_session, "Gated"))
        by_type = {r.requirement_type.value: r for r in requirements}
        assert by_type["min_xp"].threshold == 500
        assert by_type["min_xp"].alternative_group is None
        # Grouped rows are satisfied by *either*, per spec 033.
        assert by_type["percent_in_category"].alternative_group == 1
        assert by_type["player_level"].alternative_group == 1

    async def test_a_cycle_is_refused(self, db_session: AsyncSession) -> None:
        """Two challenges requiring each other unlock for nobody, ever."""
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "A",
                        "difficulty": "easy",
                        "unlocks": json.dumps(
                            [{"type": "challenge_solved", "challenge": f"{category.name}/B"}]
                        ),
                    },
                    {
                        "category": category.name,
                        "title": "B",
                        "difficulty": "easy",
                        "unlocks": json.dumps(
                            [{"type": "challenge_solved", "challenge": f"{category.name}/A"}]
                        ),
                    },
                ]
            ),
        )

        assert any(e.column == "unlocks" for e in report.errors)
        assert report.created == 0

    async def test_an_unknown_challenge_is_refused(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Orphan",
                        "difficulty": "easy",
                        "unlocks": json.dumps(
                            [{"type": "challenge_solved", "challenge": "Nowhere/Nothing"}]
                        ),
                    }
                ]
            ),
        )

        assert any(e.column == "unlocks" for e in report.errors)

    async def test_a_field_the_type_never_reads_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Confused",
                        "difficulty": "easy",
                        "unlocks": json.dumps(
                            [{"type": "min_xp", "threshold": 10, "skill": "Anything"}]
                        ),
                    }
                ]
            ),
        )

        assert any(e.column == "unlocks" for e in report.errors)

    async def test_the_ladder_leak_is_not_authorable(self, db_session: AsyncSession) -> None:
        """It is the secret route into the ladder's zone. A file that could name
        it would hand the trick to everyone who reads the file."""
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Secret",
                        "difficulty": "easy",
                        "unlocks": json.dumps([{"type": "ai_ladder_leak"}]),
                    }
                ]
            ),
        )

        assert any(e.column == "unlocks" for e in report.errors)


class TestBossColumn:
    async def test_a_tier_imports(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "The Fight",
                        "difficulty": "hard",
                        "boss_tier": "city",
                    }
                ]
            ),
        )

        assert report.ok, report.errors
        assert (await _challenge(db_session, "The Fight")).boss_tier == BossTier.CITY

    async def test_two_bosses_in_one_zone_are_refused(self, db_session: AsyncSession) -> None:
        """The partial unique index would fail halfway through the apply, which
        would break the promise that a refused file changes nothing."""
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "First Boss",
                        "difficulty": "hard",
                        "boss_tier": "city",
                    },
                    {
                        "category": category.name,
                        "title": "Second Boss",
                        "difficulty": "hard",
                        "boss_tier": "borough",
                    },
                ]
            ),
        )

        assert any(e.column == "boss_tier" for e in report.errors)
        assert report.created == 0

    async def test_a_boss_already_in_the_platform_blocks_the_slot(
        self, db_session: AsyncSession
    ) -> None:
        """The collision is usually with something that is not in the file at
        all, so checking only within the file would miss the common case."""
        category = await make_category(db_session)
        existing = await make_challenge(db_session, category=category, title="Old Boss")
        existing.boss_tier = BossTier.CITY
        await db_session.flush()

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "New Boss",
                        "difficulty": "hard",
                        "boss_tier": "borough",
                    }
                ]
            ),
        )

        assert any(
            e.column == "boss_tier" and "Old Boss" in e.problem for e in report.errors
        )
        assert report.created == 0

    async def test_one_file_may_move_the_boss(self, db_session: AsyncSession) -> None:
        """Demoting one challenge and promoting another in the same file is not
        a collision — it is how a boss gets moved."""
        category = await make_category(db_session)
        old = await make_challenge(db_session, category=category, title="Was Boss")
        old.boss_tier = BossTier.CITY
        await db_session.flush()

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {"category": category.name, "title": "Was Boss", "difficulty": "hard"},
                    {
                        "category": category.name,
                        "title": "Is Boss",
                        "difficulty": "hard",
                        "boss_tier": "city",
                    },
                ]
            ),
        )

        assert report.ok, report.errors
        assert (await _challenge(db_session, "Was Boss")).boss_tier is None
        assert (await _challenge(db_session, "Is Boss")).boss_tier == BossTier.CITY


class TestSlugColumn:
    async def test_a_slug_lets_a_title_be_renamed(self, db_session: AsyncSession) -> None:
        """Without it, editing a title in the file creates a second challenge
        beside the first — which makes a re-generated file unsafe to re-import."""
        category = await make_category(db_session)
        rows = [
            {
                "category": category.name,
                "title": "Old Name",
                "difficulty": "easy",
                "slug": "the-challenge",
                "flag": "f",
            }
        ]
        await challenge_csv.import_csv(db_session, csv_of(rows))

        rows[0]["title"] = "New Name"
        report = await challenge_csv.import_csv(db_session, csv_of(rows))

        assert report.updated == 1
        assert report.created == 0
        assert (await _challenge(db_session, "New Name")).slug == "the-challenge"

    async def test_two_rows_sharing_a_slug_are_refused(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)
        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "One",
                        "difficulty": "easy",
                        "slug": "shared",
                    },
                    {
                        "category": category.name,
                        "title": "Two",
                        "difficulty": "easy",
                        "slug": "shared",
                    },
                ]
            ),
        )

        assert any(e.column == "slug" for e in report.errors)


class TestWideColumns:
    async def test_every_column_round_trips_through_export(
        self, db_session: AsyncSession
    ) -> None:
        """The point of the whole spec: an import lands a challenge finished, and
        exporting it gives a file that re-imports to the same thing."""
        category = await make_category(db_session)
        row = {
            "category": category.name,
            "title": "Everything",
            "slug": "everything",
            "difficulty": "hard",
            "description": "A body, with a comma.",
            "xp": "320",
            "minimum_xp": "80",
            "scoring": "dynamic",
            "decay_threshold": "25",
            "decay_basis": "teams",
            "state": "published",
            "pre_release_state": "locked",
            "release_at": "2026-10-02T09:00:00",
            "max_attempts": "5",
            "flags": json.dumps([{"type": "exact", "value": "one"}, "two"]),
            "hints": json.dumps([{"title": "H", "body": "b", "cost": 15}]),
            "boss_tier": "province",
        }

        assert (await challenge_csv.import_csv(db_session, csv_of([row]))).ok
        challenge = await _challenge(db_session, "Everything")
        assert challenge.initial_points == 320
        assert challenge.minimum_points == 80
        assert challenge.scoring == ScoringMode.DYNAMIC
        assert challenge.decay_basis == DecayBasis.TEAMS
        assert challenge.decay_threshold == 25
        assert challenge.pre_release_state == PreReleaseState.LOCKED
        assert challenge.max_attempts == 5
        assert challenge.boss_tier == BossTier.PROVINCE

        exported = await challenge_csv.build_export(db_session)
        report = await challenge_csv.import_csv(db_session, exported)

        assert report.ok, report.errors
        assert report.created == 0
        assert len(await _answers(db_session, challenge)) == 2
        assert len(await _hints(db_session, challenge)) == 1

    async def test_a_floor_above_the_ceiling_is_refused(self, db_session: AsyncSession) -> None:
        category = await make_category(db_session)

        report = await challenge_csv.import_csv(
            db_session,
            csv_of(
                [
                    {
                        "category": category.name,
                        "title": "Inverted",
                        "difficulty": "easy",
                        "xp": "100",
                        "minimum_xp": "400",
                    }
                ]
            ),
        )

        assert any(e.column == "minimum_xp" for e in report.errors)

    async def test_the_old_points_column_is_refused_by_name(
        self, db_session: AsyncSession
    ) -> None:
        """Silently ignoring it would import every deliberate override as a
        default, and nobody would notice in a 242-row file."""
        category = await make_category(db_session)
        text = f"category,title,difficulty,points\n{category.name},Stale,easy,250\n"

        with pytest.raises(challenge_csv.ImportRejected, match="xp"):
            await challenge_csv.import_csv(db_session, text)

    async def test_a_spec_026_file_still_imports(self, db_session: AsyncSession) -> None:
        """The narrow columns are a subset of the wide ones, so an older file is
        simply one with a lot of blanks."""
        category = await make_category(db_session)
        text = (
            "category,title,difficulty,description,flag,state,max_attempts,release_at,skills\n"
            f"{category.name},Narrow,medium,Body.,flagvalue,,,,\n"
        )

        report = await challenge_csv.import_csv(db_session, text)

        assert report.ok, report.errors
        assert report.created == 1


async def _challenge(db: AsyncSession, title: str) -> Challenge:
    return (await db.execute(select(Challenge).where(Challenge.title == title))).scalar_one()


async def _answers(db: AsyncSession, challenge: Challenge) -> list[ChallengeAnswer]:
    return list(
        (
            await db.execute(
                select(ChallengeAnswer)
                .where(ChallengeAnswer.challenge_id == challenge.id)
                .order_by(ChallengeAnswer.display_order)
            )
        )
        .scalars()
        .all()
    )


async def _hints(db: AsyncSession, challenge: Challenge) -> list[Hint]:
    return list(
        (
            await db.execute(
                select(Hint).where(Hint.challenge_id == challenge.id).order_by(Hint.display_order)
            )
        )
        .scalars()
        .all()
    )


async def _unlocks(db: AsyncSession, challenge: Challenge) -> list[UnlockRequirement]:
    return list(
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.challenge_id == challenge.id)
            )
        )
        .scalars()
        .all()
    )
