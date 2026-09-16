"""Materialise the flags, scrub the environment, then supervise two services.

Order matters (spec 047):

  1. Read `INSTANCE_ANSWERS` — this team's four minted flags (spec 046).
  2. Write three of them where the services can read them, and the **boss flag
     somewhere neither service ever looks**.
  3. **Unset the variable and re-exec this script**, so neither child inherits
     it and no `/proc/<pid>/environ` carries it — including this process's own.
  4. Start the maintenance service on loopback and the API on the published
     port, and keep both alive.

Step 3 re-execs rather than simply unsetting because `os.environ.pop` calls
`unsetenv`, which updates the process's own copy of the environment but *not*
`/proc/<pid>/environ` — the kernel's record of what was on the stack at
`execve`. Unsetting alone would leave PID 1 advertising all four flags to
anything that could read that file. Re-exec is what actually clears it.

This stays PID 1 rather than `exec`ing the way the apothecary's entrypoint does,
because there are two processes here and a dead maintenance service would take
challenges 3 and 4 with it while the API kept answering. Step 4 restarts a child
that dies; if one dies immediately and repeatedly, this exits so the pod restarts
cleanly instead of sitting there half-alive.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import stat
import subprocess
import sys
import time

import flags
import store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("entrypoint")

API_BIND = os.environ.get("REGISTRY_API_BIND", "0.0.0.0:8080")
MAINTENANCE_PORT = 9000

#: Set on the re-exec, so the second pass knows the flags are already on disk
#: and goes straight to supervising.
SUPERVISE_ENV = "REGISTRY_SUPERVISING"

#: A child that dies this soon after starting is not going to start. Restarting
#: it forever would hide a broken image behind a container that looks alive.
FLAP_SECONDS = 5
FLAP_LIMIT = 3


def maintenance_binds() -> tuple[str, ...]:
    """Loopback only — IPv4 always, IPv6 when the runtime has it.

    `[::1]` is one of the address spellings challenge 3's hint promises will get
    through the filter, so the service listens there when it can. But a plain
    container often has no IPv6 loopback address at all, and binding an address
    that does not exist takes gunicorn down with it — which would cost us the
    maintenance service, and challenges 3 and 4 with it, to gain one alternative
    spelling. So it is probed, not assumed.

    The four IPv4 spellings (`127.1`, decimal, hex, `0.0.0.0`) work everywhere
    and are enough on their own for the challenge as written.
    """
    binds = [f"127.0.0.1:{MAINTENANCE_PORT}"]
    probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        probe.bind(("::1", 0))
    except OSError:
        logger.info("no IPv6 loopback here; maintenance listens on IPv4 only")
    else:
        binds.append(f"[::1]:{MAINTENANCE_PORT}")
    finally:
        probe.close()
    return tuple(binds)


def materialise(minted: dict[str, str]) -> None:
    """Put each flag where its challenge needs it — and the boss's out of reach."""
    import json

    store.build(minted)

    served_path = flags.SERVED_FLAGS_PATH
    os.makedirs(os.path.dirname(served_path), exist_ok=True)
    with open(served_path, "w", encoding="utf-8") as handle:
        # Only the three a service has to serve. The boss flag is not in here,
        # so neither process ever loads it and neither can disclose it.
        json.dump(
            {slug: minted[slug] for slug in (flags.PROMOTED, flags.SIGNED, flags.FETCH)},
            handle,
        )
    os.chmod(served_path, stat.S_IRUSR)

    boss_path = flags.BOSS_FLAG_PATH
    os.makedirs(os.path.dirname(boss_path), exist_ok=True)
    with open(boss_path, "w", encoding="utf-8") as handle:
        handle.write(minted[flags.BOSS] + "\n")
    os.chmod(boss_path, stat.S_IRUSR)

    logger.info("flags materialised; the boss flag is on disk and in no process")


def _gunicorn(module: str, binds: tuple[str, ...], threads: str) -> list[str]:
    """One worker, several threads, and the app loaded before the fork.

    Two processes in one container on a 250m CPU limit, inside a gVisor sandbox,
    is a tight budget: a live instance failed its readiness probe with "context
    deadline exceeded" while otherwise healthy. Every process here is one the
    sandbox has to schedule, so there is one worker each rather than two, and
    `--preload` imports the app in the master so the fork is cheap and the
    worker's pages are shared rather than copied.

    One worker is ample for the one party that owns an instance, and threads
    absorb the SSRF endpoint's outbound wait without blocking anything else.
    """
    command = ["gunicorn"]
    for bind in binds:
        command += ["--bind", bind]
    return command + [
        "--preload",
        "--workers",
        "1",
        "--threads",
        threads,
        "--timeout",
        "30",
        "--worker-tmp-dir",
        flags.RUNTIME_DIR,
        "--access-logfile",
        "-",
        f"{module}:app",
    ]


def main() -> int:
    if not os.environ.get(SUPERVISE_ENV):
        materialise(flags.load())

        # Everything is on disk now, and nothing below needs the variable. Drop
        # it and start again, so this process's own /proc entry loses it too.
        flags.scrub()
        os.environ[SUPERVISE_ENV] = "1"
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])  # noqa: S606

    return supervise()


def supervise() -> int:
    services = {
        "maintenance": _gunicorn("maintenance", maintenance_binds(), "4"),
        "api": _gunicorn("api", (API_BIND,), "8"),
    }
    children: dict[str, subprocess.Popen] = {}
    started: dict[str, float] = {}
    flaps: dict[str, int] = {name: 0 for name in services}

    def start(name: str) -> None:
        logger.info("starting %s", name)
        children[name] = subprocess.Popen(services[name])  # noqa: S603 - fixed argv
        started[name] = time.monotonic()

    for name in services:
        start(name)

    def stop(*_args: object) -> None:
        for child in children.values():
            child.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while True:
        time.sleep(1)
        for name, child in list(children.items()):
            if child.poll() is None:
                continue
            lifetime = time.monotonic() - started[name]
            logger.warning("%s exited (%s) after %.1fs", name, child.returncode, lifetime)
            if lifetime < FLAP_SECONDS:
                flaps[name] += 1
                if flaps[name] >= FLAP_LIMIT:
                    logger.error("%s will not stay up; exiting so the pod restarts", name)
                    stop()
            else:
                flaps[name] = 0
            start(name)


if __name__ == "__main__":
    sys.exit(main())
