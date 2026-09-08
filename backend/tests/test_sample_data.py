"""Sample-data generation and purge (admin tooling)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category, Challenge
from app.models.skill import Skill
from app.models.user import User, UserRole, UserStatus
from app.services import sample_data
from tests.factories import make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def count(db_session, model, *criteria) -> int:
    return await db_session.scalar(select(func.count()).select_from(model).where(*criteria))


class TestGeneration:
    async def test_it_populates_every_feature(self, db_session: AsyncSession) -> None:
        summary = await sample_data.generate(db_session)

        assert summary.challenges > 0
        assert summary.categories > 0
        # Skills come from the seed migration; the sample attaches real ones.
        assert summary.skills > 0
        assert summary.classes > 0
        assert summary.players > 0
        assert summary.solves > 0
        assert summary.gates > 0
        assert summary.hints > 0

    async def test_generating_twice_replaces_rather_than_duplicates(
        self, db_session: AsyncSession
    ) -> None:
        """The button has to be safe to press again."""
        first = await sample_data.generate(db_session)
        await sample_data.generate(db_session)

        total = await count(
            db_session, Challenge, Challenge.slug.startswith(sample_data.SAMPLE_PREFIX)
        )
        assert total == first.challenges


class TestPurge:
    async def test_it_removes_what_it_made(self, db_session: AsyncSession) -> None:
        await sample_data.generate(db_session)

        await sample_data.purge(db_session)

        assert (
            await count(db_session, Challenge, Challenge.slug.startswith(sample_data.SAMPLE_PREFIX))
            == 0
        )
        assert (
            await count(db_session, Category, Category.slug.startswith(sample_data.SAMPLE_PREFIX))
            == 0
        )
        # Skills are seeded content now, not sample content — the purge must
        # leave them alone (spec 018).
        assert await count(db_session, Skill, Skill.name == "Cryptanalysis") == 1
        assert (
            await count(
                db_session,
                User,
                User.email.endswith(f"@{sample_data.SAMPLE_EMAIL_DOMAIN}"),
            )
            == 0
        )

    async def test_it_leaves_real_data_alone(self, db_session: AsyncSession) -> None:
        """The precision that makes the purge safe to offer at all."""
        real = await make_challenge(db_session, title="Real Challenge")
        real_user = await make_user(db_session, email="someone@example.com")
        await sample_data.generate(db_session)

        await sample_data.purge(db_session)

        assert await db_session.get(Challenge, real.id) is not None
        assert await db_session.get(User, real_user.id) is not None


class TestApi:
    async def test_an_admin_generates_and_purges(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        created = await client.post("/api/admin/sample-data")
        assert created.status_code == 200
        assert created.json()["challenges"] > 0

        removed = await client.delete("/api/admin/sample-data")
        assert removed.status_code == 200

    async def test_a_player_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.post("/api/admin/sample-data")).status_code == 403

    async def test_production_refuses(self) -> None:
        with pytest.raises(sample_data.SampleDataUnavailable):
            sample_data.ensure_allowed(is_production=True)
