"""Seed load-test users and mint real sessions (spec 012).

A load test needs many signed-in players, and this platform has no password to
script and — deliberately — no "log in as anyone" endpoint. So this creates N
active guest users and issues each a genuine session with the app's own
``issue_session``, writing a CSV the locustfile reads. Each virtual user then
carries a real cookie, exercising the same auth path a browser does.

**Point this at a disposable database, never production.** It writes users and
sessions; the ``--purge`` flag removes everything it made (matched by the
``loadtest+`` email prefix).

Run from the backend project so ``app`` is importable::

    cd backend
    uv run python ../loadtest/seed.py --count 250 --out ../loadtest/sessions.csv
    uv run python ../loadtest/seed.py --purge
"""

import argparse
import asyncio
import csv
import sys
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import User, UserSource, UserStatus
from app.services.sessions import issue_session

EMAIL_PREFIX = "loadtest+"


async def _seed(count: int, out: Path) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    rows: list[dict[str, str]] = []
    async with maker() as session:
        for index in range(count):
            user = User(
                email=f"{EMAIL_PREFIX}{index}-{uuid.uuid4().hex[:8]}@example.com",
                display_name=f"Load Runner {index}",
                source=UserSource.GUEST,
                status=UserStatus.ACTIVE,
            )
            session.add(user)
            await session.flush()
            issued = await issue_session(session, settings, user.id)
            rows.append(
                {
                    "access_token": issued.access_token,
                    "csrf_token": issued.csrf_token,
                }
            )
        await session.commit()

    await engine.dispose()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["access_token", "csrf_token"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Seeded {count} users and sessions -> {out}")


async def _purge() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.async_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        ids = (
            (await session.execute(select(User.id).where(User.email.like(f"{EMAIL_PREFIX}%"))))
            .scalars()
            .all()
        )
        # Sessions, solves, submissions etc. cascade from the user row.
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()
    await engine.dispose()
    print(f"Purged {len(ids)} load-test users.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or purge load-test users")
    parser.add_argument("--count", type=int, default=250, help="how many users to seed")
    parser.add_argument("--out", type=Path, default=Path("loadtest/sessions.csv"))
    parser.add_argument("--purge", action="store_true", help="remove all load-test users")
    args = parser.parse_args()

    if args.purge:
        asyncio.run(_purge())
    else:
        asyncio.run(_seed(args.count, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
