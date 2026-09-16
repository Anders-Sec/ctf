"""Fixtures for the apothecary's own tests (spec 045).

These run the real entrypoint against a temporary runtime directory, so what is
tested is the container as it actually starts: the database built from the seed,
the two flag files written, and the environment scrubbed.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

IMAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IMAGE_ROOT))

#: Four distinguishable values, so a test that gets the wrong challenge's flag
#: fails loudly rather than passing by coincidence.
MINTED = {
    "someone-elses-chart": "flag{not_your_chart_aaaa1111}",
    "quotes-are-load-bearing": "flag{quotes_are_load_bearing_bbbb2222}",
    "up-and-out": "flag{up_and_out_cccc3333}",
    "curly-braces": "flag{the_template_ate_it_dddd4444}",
}


def _boot(runtime: Path, answers: str | None):
    """Start the image the way the container does, into `runtime`."""
    os.environ["APOTHECARY_RUNTIME"] = str(runtime)
    if answers is None:
        os.environ.pop("INSTANCE_ANSWERS", None)
    else:
        os.environ["INSTANCE_ANSWERS"] = answers

    # Reimported so the module-level paths pick up APOTHECARY_RUNTIME.
    import flags

    importlib.reload(flags)
    import db

    importlib.reload(db)
    import entrypoint

    importlib.reload(entrypoint)

    entrypoint.materialise(flags.load())
    flags.scrub()

    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    return app_module, flags


def traverse(target: str) -> str:
    """The `f=` payload a player would send to reach `target`.

    Built from a relative path so the test reads the same on Windows as in the
    container, and then doubled: the handler strips `../` once, so `....//` is
    what arrives as `../`. This is the technique the published hint describes.
    """
    import app as app_module

    relative = os.path.relpath(target, app_module.PAGES_DIR).replace(os.sep, "/")
    return relative.replace("../", "....//")


#: How to print a file, for the template-injection tests. The container is
#: Linux; this keeps the same popen-based proof runnable on a Windows desktop.
READ_COMMAND = "type" if os.name == "nt" else "cat"


@pytest.fixture
def portal(tmp_path):
    """The app, started with known flags, as the container would start it."""
    app_module, _ = _boot(tmp_path, json.dumps(MINTED))
    yield app_module.app


@pytest.fixture
def portal_without_platform(tmp_path):
    """The same image with no INSTANCE_ANSWERS — a local run, or CI."""
    app_module, flags_module = _boot(tmp_path, None)
    yield app_module.app, flags_module


@pytest.fixture
def client(portal):
    with portal.test_client() as test_client:
        yield test_client


@pytest.fixture
def signed_in(client):
    """A session as the seeded low-privilege patient, the way a player starts."""
    client.post("/login", data={"username": "p.abernathy", "password": "springfield"})
    return client


def shipped_files(image_root):
    """Every file the Dockerfile actually copies into the image.

    Scoped to what ships rather than to the working directory, because the rule
    is about what is *in the container*. A checkout also holds this image's
    README, its tests and its tooling, none of which a player can ever see —
    and scanning those made a docs example mentioning the event's own domain
    fail a check meant to catch a real organisation's name in the product.
    """
    import pathlib
    import shlex

    root = pathlib.Path(image_root)
    dockerfile = root / "Dockerfile"
    if not dockerfile.exists():
        # Running inside the built image: there is no Dockerfile here, and
        # everything present *is* the shipped set. Tests are mounted in, so they
        # are the only thing to leave out.
        return [
            p
            for p in root.rglob("*")
            if p.is_file()
            and "tests" not in p.parts
            and "__pycache__" not in p.parts
            and p.suffix not in {".db", ".pyc"}
        ]

    sources: list[pathlib.Path] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        if not line.startswith("COPY "):
            continue
        parts = [p for p in shlex.split(line)[1:] if not p.startswith("--")]
        for source in parts[:-1]:  # the last argument is the destination
            target = root / source
            if target.is_dir():
                sources.extend(p for p in target.rglob("*") if p.is_file())
            elif target.is_file():
                sources.append(target)
    return sources
