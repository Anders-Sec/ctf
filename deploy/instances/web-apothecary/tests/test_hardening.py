"""The routes that must stay shut (spec 045).

Four flaws, and only four. A player who finds an unintended hole here skips the
area, and a leak that runs *upward* — an easier challenge handing over a harder
one's flag — devalues the hardest thing in the area. These are the tests that
notice.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from tests.conftest import MINTED, shipped_files, traverse

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="the container is Linux; these are POSIX paths"
)


class TestTheTemplateInjectionFlagStaysPut:
    """The traversal must not reach challenge 4's flag. It is the one leak that
    runs upward: `hard` collecting `very_hard` for free."""

    def test_the_traversal_cannot_read_it_by_any_route(self, signed_in, portal) -> None:
        import flags

        payload = traverse(flags.SSTI_FLAG_PATH)
        attempts = [
            flags.SSTI_FLAG_PATH,
            payload,
            payload.replace("/.flag", "/./.flag"),
            payload.replace("/.flag", "/x/../.flag"),
            "../" + payload,
            traverse(flags.TRAVERSAL_FLAG_PATH).replace("flag.txt", ".flag"),
        ]

        for attempt in attempts:
            response = signed_in.get(f"/page?f={attempt}")
            assert MINTED["curly-braces"].encode() not in response.data, attempt

    def test_the_environment_carries_no_flag(self) -> None:
        """The entrypoint's scrub. Without it the traversal reads
        /proc/self/environ and walks away with the hardest flag in the area."""
        environment = "\n".join(f"{key}={value}" for key, value in os.environ.items())
        for value in MINTED.values():
            assert value not in environment

    @posix_only
    def test_proc_self_environ_gives_the_traversal_nothing(self, signed_in) -> None:
        """The same guarantee, through the route that would exploit its absence."""
        response = signed_in.get(f"/page?f={traverse('/proc/self/environ')}")

        for value in MINTED.values():
            assert value.encode() not in response.data

    def test_it_is_in_no_config_value_and_no_database_row(self, portal) -> None:
        import db
        import flags

        for value in portal.config.values():
            assert MINTED["curly-braces"] not in str(value)

        connection = db.connect()
        try:
            for table in ("record", "portal_user", "portal_setting"):
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
                for row in rows:
                    assert MINTED["curly-braces"] not in " ".join(str(v) for v in tuple(row))
        finally:
            connection.close()

        # It exists — as a file, which is the only way to it.
        with open(flags.SSTI_FLAG_PATH, encoding="utf-8") as handle:
            assert MINTED["curly-braces"] in handle.read()


class TestTheFilterIsExactlySinglePass:
    """This is the difficulty of challenge 3. A recursive strip would make
    `....//` fail and the published second hint wrong."""

    def test_one_pass_strips_and_nested_survives(self, signed_in, portal) -> None:
        import flags

        payload = traverse(flags.TRAVERSAL_FLAG_PATH)
        stripped = signed_in.get("/page?f=" + payload.replace("....//", "../"))
        survived = signed_in.get(f"/page?f={payload}")

        assert stripped.status_code == 404
        assert MINTED["up-and-out"].encode() in survived.data

    def test_a_recursive_strip_would_break_the_published_hint(self, signed_in, portal) -> None:
        """If the filter ever loops, `....//` collapses to nothing and the
        second hint stops being true. This is what notices."""
        import flags

        response = signed_in.get(f"/page?f={traverse(flags.TRAVERSAL_FLAG_PATH)}")

        assert response.status_code == 200


class TestOnlyTheLoginIsInjectable:
    def test_the_other_routes_take_a_quote_without_breaking(self, signed_in) -> None:
        payload = "' OR '1'='1"

        record = signed_in.get(f"/record?id={payload}")
        page = signed_in.get(f"/page?f={payload}")
        message = signed_in.post("/message", data={"recipient": payload, "body": payload})

        assert record.status_code == 404
        assert page.status_code == 404
        assert message.status_code == 200
        for response in (record, page, message):
            assert b"Database error" not in response.data

    def test_a_record_id_that_is_not_a_number_is_a_404_not_a_500(self, signed_in) -> None:
        assert signed_in.get("/record?id=nonsense").status_code == 404


class TestSessionsAndGates:
    def test_every_authenticated_route_redirects_when_signed_out(self, client) -> None:
        for path in ("/portal", "/record", "/admin", "/page", "/message"):
            response = client.get(path)
            assert response.status_code == 302, path
            assert "/login" in response.headers["Location"]

    def test_the_admin_dashboard_is_gated_on_the_role(self, signed_in) -> None:
        assert signed_in.get("/admin").status_code == 403

    def test_healthz_answers_without_a_session(self, client) -> None:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.data == b"ok"


class TestItSurvivesBeingHammered:
    def test_a_huge_message_body_is_refused_not_fatal(self, signed_in) -> None:
        """A megabyte of payload gets a 413 from the form parser. What matters
        is that it is not a 500 and the portal is still there afterwards."""
        response = signed_in.post(
            "/message", data={"recipient": "1042", "body": "A" * 1_000_000}
        )

        assert response.status_code < 500
        assert signed_in.get("/healthz").status_code == 200

    def test_an_unterminated_expression_is_an_error_page(self, signed_in) -> None:
        response = signed_in.post("/message", data={"recipient": "1042", "body": "{{ 1 +"})

        assert response.status_code == 200
        assert b"could not be composed" in response.data

    def test_a_missing_page_parameter_falls_back(self, signed_in) -> None:
        assert signed_in.get("/page").status_code == 200

    def test_the_database_is_read_only(self, portal) -> None:
        """Nothing a player reaches through the app can corrupt the data."""
        import db

        connection = db.connect()
        try:
            try:
                connection.execute("DELETE FROM record")
                raise AssertionError("the database accepted a write")
            except sqlite3.OperationalError as exc:
                assert "readonly" in str(exc).lower()
        finally:
            connection.close()


class TestNothingRealIsNamed:
    """The brief is explicit: it is a fictional clinic.

    Checked against the files the image *ships*, not the working directory. A
    checkout also holds the README and the tests, and neither reaches a player.
    """

    def test_no_real_organisation_appears_in_the_image(self, portal) -> None:
        import pathlib

        import flags

        root = pathlib.Path(flags.__file__).resolve().parent
        banned = ("northwestern", "nmh.org", "nm.org")

        shipped = shipped_files(root)
        assert shipped, "found no shipped files; the Dockerfile parse is wrong"

        for path in shipped:
            body = path.read_text(encoding="utf-8", errors="ignore").lower()
            for word in banned:
                assert word not in body, f"{path.name} mentions {word!r}"
