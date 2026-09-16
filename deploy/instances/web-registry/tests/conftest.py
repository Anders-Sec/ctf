"""Fixtures for the registry's own tests (spec 047).

Two services means two kinds of test. Most run both Flask apps in-process, with
the maintenance app on a **real loopback socket** — a stub would only prove the
stub, and challenge 3 is entirely about which spellings of loopback reach a real
listener.

The tests that are about the two-process topology itself — maintenance not being
reachable from outside, readiness noticing when it dies — run the built
container, and are marked `container`.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

import pytest

IMAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IMAGE_ROOT))

#: Four distinguishable values, so a test that gets the wrong challenge's flag
#: fails loudly rather than passing by coincidence.
MINTED = {
    "promoted": "flag{i_promoted_myself_aaaa1111}",
    "signed-by-me": "flag{signed_by_me_bbbb2222}",
    "fetch-it-for-me": "flag{the_server_fetched_it_cccc3333}",
    "no-route-to-it": "flag{trust_no_object_dddd4444}",
}

#: Every spelling of loopback the first hint promises will get past a filter
#: that checks hostnames rather than addresses.
LOOPBACK_SPELLINGS = ("127.1", "2130706433", "0x7f000001", "0.0.0.0", "[::1]")

DEMO_USER = "t.brennan"
DEMO_PASSWORD = "bureau2019"
SIGNED_FLAG_OWNER = "m.calloway"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass


class _DualStackServer(WSGIServer):
    """Listens on both loopback families on one port.

    The image binds maintenance on `127.0.0.1` and `[::1]` explicitly; this is
    the test's equivalent, so `[::1]` is exercised against a listener that is
    really there rather than being assumed to work.
    """

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _boot(runtime: Path, answers: str | None):
    """Start the image the way the container does, into `runtime`."""
    os.environ["REGISTRY_RUNTIME"] = str(runtime)
    if answers is None:
        os.environ.pop("INSTANCE_ANSWERS", None)
    else:
        os.environ["INSTANCE_ANSWERS"] = answers

    import flags

    importlib.reload(flags)
    import store

    importlib.reload(store)
    import entrypoint

    importlib.reload(entrypoint)

    entrypoint.materialise(flags.load())
    flags.scrub()

    import maintenance

    importlib.reload(maintenance)
    import api

    importlib.reload(api)

    api.app.config["TESTING"] = True
    maintenance.app.config["TESTING"] = True
    return api, maintenance, flags


@pytest.fixture
def registry(tmp_path):
    """Both services, maintenance on a real dual-stack loopback port."""
    api, maintenance, flags_module = _boot(tmp_path, json.dumps(MINTED))

    server = _DualStackServer(("::", 0), _QuietHandler)
    server.set_app(maintenance.app)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield api, maintenance, flags_module, port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(registry):
    api, _, _, _ = registry
    with api.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def port(registry):
    return registry[3]


@pytest.fixture
def loopback(port):
    """A spelling that gets past the blocklist *and* works on this machine.

    Which spellings work is a property of the environment, not of the image:
    Windows will not resolve `127.1` or connect to `0.0.0.0`, and a container
    with no IPv6 loopback will not accept `[::1]`. Tests that merely need to
    reach the maintenance service take whichever one works here; the test that
    is *about* the spellings tries them all and says which the machine cannot do.
    """
    for spelling in LOOPBACK_SPELLINGS:
        if can_reach(spelling, port):
            return spelling
    pytest.skip("no loopback spelling reaches the maintenance service here")
    return None


def can_reach(host: str, port: int) -> bool:
    """Whether *this machine* can reach loopback written this way.

    Linux resolves `127.1`, decimal and hex, and routes a connection to
    `0.0.0.0` to localhost. Windows does neither. The container is Linux and
    handles all five spellings — verified — so a desktop that cannot is a fact
    about the desktop, not about the image, and the address-form tests say so
    rather than failing.
    """
    try:
        with socket.create_connection((host.strip("[]"), port), timeout=2):
            return True
    except OSError:
        return False


def token_for(client, username: str = DEMO_USER, password: str = DEMO_PASSWORD) -> str:
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fetch_through_api(client, token: str, url: str, **extra):
    """Ask the API to fetch a URL — the SSRF, as a player uses it."""
    return client.post("/api/fetch", json={"url": url, **extra}, headers=auth(token))


def submit_job(client, token: str, url: str, payload: str, **extra):
    """Submit a job through the SSRF, carrying the token *inward*.

    The maintenance service has no session with the player; it only sees what
    the API's fetch sends it. Presenting an administrator token on the inner
    request is a step the boss requires and challenge 3 does not.
    """
    return fetch_through_api(
        client,
        token,
        url,
        method="POST",
        body=payload,
        headers={"Authorization": f"Bearer {token}"},
        **extra,
    )
