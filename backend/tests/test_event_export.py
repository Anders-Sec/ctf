"""Getting the results out (spec 056)."""

import csv
import io
import zipfile

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


def rows_of(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


class TestStandings:
    async def test_it_matches_the_admin_board_exactly(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """One number, two surfaces. An export that disagreed with the screen
        somebody read the winner off would be worse than none."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Rin", status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)
        await scoreboard_cache.mark_dirty(get_redis(settings))

        board = (await client.get("/api/admin/scoreboard")).json()
        export = rows_of((await client.get("/api/admin/export/standings.csv")).text)

        row = next(r for r in export[1:] if r[2] == "Rin")
        board_row = next(r for r in board["players"] if r["display_name"] == "Rin")
        assert int(row[7]) == board_row["score"]
        assert int(row[1]) == board_row["rank"]

    async def test_it_carries_a_bom_so_excel_opens_it_cleanly(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        await make_user(db_session, display_name="Ríñ Vänce", status=UserStatus.ACTIVE)

        text = (await client.get("/api/admin/export/standings.csv")).text

        assert text.startswith("﻿")


class TestSubmissions:
    async def test_the_default_export_carries_no_submitted_values(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """In aggregate `submitted_value` is a list of every flag in the event,
        because every correct submission is one."""
        await staff(db_session, client, sign_in)

        response = await client.get("/api/admin/export/submissions.csv")
        header = rows_of(response.text)[0]

        assert "value" not in header
        assert "ip" not in header
        assert "near_miss" in header

    async def test_the_full_form_is_not_reachable_by_a_query_flag(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        response = await client.get("/api/admin/export/submissions.csv?full=true")

        assert response.status_code == 404

    async def test_the_full_form_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in, role=UserRole.ORGANIZER)

        assert (await client.get("/api/admin/export/submissions-full.csv")).status_code == 403

    async def test_taking_the_full_form_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Legitimate for post-event analysis, and not a file to email around."""
        await staff(db_session, client, sign_in)

        await client.get("/api/admin/export/submissions-full.csv")

        log = (await client.get("/api/admin/audit-log?action=export.")).json()
        assert any(row["action"] == "export.submissions_full" for row in log["entries"])

    async def test_the_full_form_does_carry_the_values(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        header = rows_of((await client.get("/api/admin/export/submissions-full.csv")).text)[0]

        assert "value" in header
        assert "ip" in header


class TestAwards:
    async def test_it_groups_the_awards_rather_than_making_one_wide_table(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """It is read aloud, so it is a document more than a dataset."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Vex", status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)
        await scoreboard_cache.mark_dirty(get_redis(settings))

        text = (await client.get("/api/admin/export/awards.csv")).text

        assert "OVERALL" in text
        assert "TOP PER ZONE" in text
        assert "FIRST BLOOD" in text

    async def test_a_zone_nobody_touched_still_gets_a_line(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Nothing silently missing from a sheet being read out."""
        await staff(db_session, client, sign_in)
        await make_challenge(db_session, initial_points=100)

        text = (await client.get("/api/admin/export/awards.csv")).text

        assert "nobody" in text


class TestArchive:
    async def test_it_holds_every_export_and_a_manifest(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        response = await client.get("/api/admin/export/archive.zip")

        bundle = zipfile.ZipFile(io.BytesIO(response.content))
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "standings.csv" in names
        assert "awards.csv" in names
        assert "audit-log.csv" in names

    async def test_it_excludes_the_full_submissions_form(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Only ever downloaded deliberately, and on its own."""
        await staff(db_session, client, sign_in)

        response = await client.get("/api/admin/export/archive.zip")

        bundle = zipfile.ZipFile(io.BytesIO(response.content))
        submissions = bundle.read("submissions.csv").decode("utf-8")
        assert "value" not in rows_of(submissions)[0]
        assert "submissions-full.csv" not in bundle.namelist()

    async def test_the_manifest_counts_what_each_file_holds(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import json

        await staff(db_session, client, sign_in)
        await make_user(db_session, display_name="Counted", status=UserStatus.ACTIVE)

        response = await client.get("/api/admin/export/archive.zip")
        bundle = zipfile.ZipFile(io.BytesIO(response.content))
        manifest = json.loads(bundle.read("manifest.json"))

        assert manifest["files"]["players.csv"] >= 1
        assert "generated_at" in manifest


class TestAvailability:
    async def test_exports_work_before_the_event_has_started(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Checking the awards sheet computes what you expect happens *before*
        the afternoon you need it."""
        await staff(db_session, client, sign_in)

        assert (await client.get("/api/admin/export/awards.csv")).status_code == 200

    async def test_an_unknown_export_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        assert (await client.get("/api/admin/export/nonsense.csv")).status_code == 404

    async def test_a_player_gets_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/export/standings.csv")).status_code == 403
        assert (await client.get("/api/admin/export/archive.zip")).status_code == 403

    async def test_the_filename_names_the_event(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """So three downloads in one afternoon do not become "export (2)"."""
        await staff(db_session, client, sign_in)

        response = await client.get("/api/admin/export/players.csv")

        assert "attachment" in response.headers["content-disposition"]
        assert "players" in response.headers["content-disposition"]


class TestParties:
    async def test_disbanded_parties_are_included(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """They are part of what happened."""
        await staff(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, leader, name="Was Here")

        text = (await client.get("/api/admin/export/parties.csv")).text

        assert "Was Here" in text
