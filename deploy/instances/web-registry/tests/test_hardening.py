"""The routes that must stay shut (spec 047).

The first class here is the one the brief names explicitly: reaching the
maintenance service must not, by itself, yield the boss flag or a shell. If it
does, challenge 4 is not a boss — it is challenge 3 with extra steps.
"""

from __future__ import annotations

import base64
import json
import os
import pickle  # noqa: S403 - building malformed payloads on purpose

import jwt
import pytest

from tests.conftest import (
    MINTED,
    SIGNED_FLAG_OWNER,
    auth,
    fetch_through_api,
    submit_job,
    token_for,
)


def _admin(client) -> str:
    token = token_for(client)
    client.patch("/api/profile", json={"role": "admin"}, headers=auth(token))
    return token_for(client)


class TestReachingMaintenanceIsNotEnough:
    """The brief's stated test for whether the boss is a boss."""

    def test_no_documented_endpoint_hands_over_the_boss_flag(self, client, port, loopback) -> None:
        admin = _admin(client)
        listing = json.loads(
            fetch_through_api(client, admin, f"http://{loopback}:{port}/").get_json()["body"]
        )

        seen = [json.dumps(listing)]
        for route in ("/", "/status", "/status/flag", "/healthz"):
            response = fetch_through_api(client, admin, f"http://{loopback}:{port}{route}")
            seen.append(response.get_data(as_text=True))

        for body in seen:
            assert MINTED["no-route-to-it"] not in body

    def test_nothing_short_of_a_gadget_runs_a_command(self, client, port, loopback) -> None:
        """No ?cmd=, no diagnostics parameter, no file-read parameter.

        These are the shortcuts the brief says must not exist. Each is tried the
        way somebody probing the service would try it.
        """
        admin = _admin(client)
        probes = [
            "/jobs?cmd=id",
            "/jobs?command=id",
            "/exec?cmd=id",
            "/run?cmd=id",
            "/debug?cmd=id",
            "/status?cmd=id",
            "/ping?host=127.0.0.1;id",
            "/status/flag?file=/tmp/registry/secrets/.flag",
            "/read?path=/tmp/registry/secrets/.flag",
            "/files?path=/tmp/registry/secrets/.flag",
        ]

        for probe in probes:
            response = fetch_through_api(client, admin, f"http://{loopback}:{port}{probe}")
            body = response.get_data(as_text=True)
            assert MINTED["no-route-to-it"] not in body, probe
            assert "uid=" not in body, probe

    def test_an_empty_or_junk_job_does_not_execute_anything(self, client, port, loopback) -> None:
        admin = _admin(client)

        for payload in ("", "bm90IGEgcGlja2xl", "!!!not base64!!!"):
            response = submit_job(client, admin, f"http://{loopback}:{port}/jobs", payload)
            body = response.get_data(as_text=True)
            assert MINTED["no-route-to-it"] not in body
            assert response.status_code == 200  # the fetch succeeded; the job did not


class TestTheBossFlagHasNoRoute:
    def test_no_api_route_returns_it(self, client) -> None:
        admin = _admin(client)
        responses = [
            client.get("/"),
            client.get("/healthz"),
            client.get("/api/profile", headers=auth(admin)),
            client.get("/api/records", headers=auth(admin)),
            client.get("/api/records/mine", headers=auth(admin)),
            client.get("/api/admin/audit", headers=auth(admin)),
        ]

        for response in responses:
            assert MINTED["no-route-to-it"].encode() not in response.data

    def test_the_fetch_endpoint_cannot_read_it_off_disk(self, client, registry, loopback) -> None:
        """Without the scheme restriction, file:// would end the boss here."""
        _, _, flags_module, _ = registry
        admin = _admin(client)

        for url in (
            f"file://{flags_module.BOSS_FLAG_PATH}",
            f"file:///{flags_module.BOSS_FLAG_PATH.lstrip('/')}",
            "ftp://127.1/secrets",
            "gopher://127.1:9000/_POST%20/jobs",
            f"http://{loopback}/../..{flags_module.BOSS_FLAG_PATH}",
        ):
            response = fetch_through_api(client, admin, url)
            assert MINTED["no-route-to-it"] not in response.get_data(as_text=True), url

    def test_it_is_in_no_environment_variable(self) -> None:
        environment = "\n".join(f"{key}={value}" for key, value in os.environ.items())

        for value in MINTED.values():
            assert value not in environment

    def test_the_entrypoint_re_execs_rather_than_only_unsetting(self, monkeypatch) -> None:
        """`unsetenv` does not clear /proc/<pid>/environ — only a re-exec does.

        Without this, PID 1 goes on advertising all four flags for the life of
        the container to anything that can read that file. Found by checking a
        real container rather than by reasoning about it; this is what stops it
        coming back.
        """
        import entrypoint

        calls = []
        monkeypatch.delenv(entrypoint.SUPERVISE_ENV, raising=False)
        monkeypatch.setattr(entrypoint, "materialise", lambda *_: None)
        monkeypatch.setattr(entrypoint.flags, "load", dict)
        monkeypatch.setattr(entrypoint.os, "execv", lambda *args: calls.append(args))
        monkeypatch.setattr(entrypoint, "supervise", lambda: 0)

        entrypoint.main()

        assert calls, "the entrypoint did not re-exec after scrubbing"
        assert os.environ.get(entrypoint.SUPERVISE_ENV) == "1"

    def test_it_is_not_in_the_runtime_flag_file(self, registry) -> None:
        """Neither process ever loads it, which is why neither can leak it."""
        _, _, flags_module, _ = registry

        with open(flags_module.SERVED_FLAGS_PATH, encoding="utf-8") as handle:
            served = json.load(handle)

        assert MINTED["no-route-to-it"] not in json.dumps(served)
        assert set(served) == {"promoted", "signed-by-me", "fetch-it-for-me"}

    def test_neither_service_holds_it_in_memory(self, registry) -> None:
        api, maintenance, _, _ = registry

        assert MINTED["no-route-to-it"] not in json.dumps(api.SERVED)
        assert MINTED["no-route-to-it"] not in json.dumps(maintenance.SERVED)
        for config in (api.app.config, maintenance.app.config):
            assert MINTED["no-route-to-it"] not in str(dict(config))

    def test_it_is_on_disk_though(self, registry) -> None:
        """The counterpart: unreachable is not the same as absent."""
        _, _, flags_module, _ = registry

        with open(flags_module.BOSS_FLAG_PATH, encoding="utf-8") as handle:
            assert MINTED["no-route-to-it"] in handle.read()


class TestOneAndTwoStayIndependent:
    def test_an_admin_cannot_read_another_users_private_records(self, client) -> None:
        """Promotion must not hand over the forgery challenge's flag."""
        admin = _admin(client)

        mine = client.get("/api/records/mine", headers=auth(admin))
        everything = client.get("/api/records", headers=auth(admin))

        assert MINTED["signed-by-me"].encode() not in mine.data
        assert MINTED["signed-by-me"].encode() not in everything.data

    def test_forgery_alone_does_not_reach_the_admin_flag(self, client) -> None:
        """And the reverse: becoming Calloway is not becoming an administrator."""
        token = token_for(client)
        claims = jwt.decode(token, options={"verify_signature": False})
        claims["sub"] = SIGNED_FLAG_OWNER
        forged = jwt.encode(claims, "changeme", algorithm="HS256")

        refused = client.get("/api/admin/audit", headers=auth(forged))

        assert refused.status_code == 403
        assert MINTED["promoted"].encode() not in refused.data


class TestTheSsrfFilterExists:
    def test_the_blocklist_is_real(self, client, port) -> None:
        """A filter the hints describe has to actually be there."""
        token = token_for(client)

        for host in ("localhost", "LOCALHOST", "127.0.0.1"):
            response = fetch_through_api(client, token, f"http://{host}:{port}/status/flag")
            assert response.status_code == 400, host
            assert MINTED["fetch-it-for-me"] not in response.get_data(as_text=True)

    def test_fetching_requires_a_token(self, client, port, loopback) -> None:
        response = client.post("/api/fetch", json={"url": f"http://{loopback}:{port}/"})

        assert response.status_code == 401


class TestOnlyTheProfileMassAssigns:
    def test_an_unknown_field_is_ignored_rather_than_stored(self, client) -> None:
        token = token_for(client)

        client.patch("/api/profile", json={"is_superuser": True}, headers=auth(token))
        profile = client.get("/api/profile", headers=auth(token)).get_json()

        assert "is_superuser" not in profile

    def test_the_job_endpoint_refuses_a_non_admin_token(self, client, port, loopback) -> None:
        token = token_for(client)

        response = submit_job(client, token, f"http://{loopback}:{port}/jobs", "Zm9v")

        assert json.loads(response.get_json()["body"])["error"].startswith("An administrator")


class TestItSurvivesBeingHammered:
    @pytest.mark.parametrize(
        "payload",
        [
            {"url": "not-a-url"},
            {"url": ""},
            {"url": "http://"},
            {"url": "http://127.1:1/", "method": "DELETE"},
            {},
        ],
    )
    def test_a_malformed_fetch_is_an_error_not_a_traceback(self, client, payload) -> None:
        token = token_for(client)

        response = client.post("/api/fetch", json=payload, headers=auth(token))

        assert response.status_code < 500
        assert b"Traceback" not in response.data

    def test_a_token_that_is_not_a_token_is_a_401(self, client) -> None:
        for bad in ("Bearer nonsense", "Bearer a.b.c", "nonsense", ""):
            response = client.get("/api/profile", headers={"Authorization": bad})
            assert response.status_code == 401

    def test_a_body_that_is_not_json_is_a_400(self, client) -> None:
        token = token_for(client)

        response = client.patch(
            "/api/profile", data="not json", headers=auth(token), content_type="application/json"
        )

        assert response.status_code == 400

    def test_a_huge_job_is_refused_not_fatal(self, client, port, loopback) -> None:
        admin = _admin(client)

        response = submit_job(client, admin, f"http://{loopback}:{port}/jobs", "A" * 200_000)

        assert response.status_code < 500
        assert MINTED["no-route-to-it"] not in response.get_data(as_text=True)

    def test_a_pickle_that_raises_on_load_is_reported(self, client, port, loopback) -> None:
        class Explodes:
            def __reduce__(self):
                raise ValueError("no")

        admin = _admin(client)
        try:
            payload = base64.b64encode(pickle.dumps(Explodes())).decode()
        except ValueError:
            payload = base64.b64encode(b"\x80\x04\x95broken").decode()

        response = submit_job(client, admin, f"http://{loopback}:{port}/jobs", payload)

        assert response.status_code < 500


class TestNothingRealIsNamed:
    def test_no_real_organisation_appears_anywhere(self, registry) -> None:
        import pathlib

        _, _, flags_module, _ = registry
        root = pathlib.Path(flags_module.__file__).resolve().parent
        banned = ("northwestern", "nmh.org", "nm.org")

        for path in root.rglob("*"):
            if not path.is_file() or path.suffix in {".db", ".pyc"}:
                continue
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore").lower()
            for word in banned:
                assert word not in body, f"{path.name} mentions {word!r}"
