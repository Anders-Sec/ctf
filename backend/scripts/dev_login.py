"""Mint a local login link for a dev account.

Magic-link email needs SMTP, which a local checkout does not have, so there is
otherwise no way to sign in against `docker compose` Postgres. This creates (or
promotes) an account and prints a link to paste into the browser.

Refuses to run against a production environment: the whole point is that it
hands out a session without an email round-trip.

    python -m scripts.dev_login admin@ctf-nm.org --role admin
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services import magic_link


async def issue(email: str, role: UserRole, display_name: str) -> str:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("dev_login refuses to run in production.")

    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as db, db.begin():
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                source=UserSource.GUEST,
                status=UserStatus.ACTIVE,
                role=role,
                approved_at=datetime.now(UTC),
            )
            db.add(user)
        else:
            user.role = role
            user.status = UserStatus.ACTIVE
            user.approved_at = user.approved_at or datetime.now(UTC)
        await db.flush()

        return await magic_link.issue_magic_link(db, settings, email)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument(
        "--role",
        default="admin",
        choices=[r.value for r in UserRole],
    )
    parser.add_argument("--name", default="Dungeon Admin")
    args = parser.parse_args()

    link = asyncio.run(issue(args.email, UserRole(args.role), args.name))
    print(link)


if __name__ == "__main__":
    main()
