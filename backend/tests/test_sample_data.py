"""Sample-data generation and purge (admin tooling)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category, Challenge, ChallengeState
from app.models.character_class import CharacterClass
from app.models.play import Solve
from app.models.skill import ChallengeSkill, Skill
from app.models.user import User, UserRole, UserStatus
from app.services import sample_data
from tests.factories import make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def _count(db_session, model) -> int:
    return (await db_session.execute(select(func.count(model.id)))).scalar()


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
        # The sample data no longer owns classes: 024 seeded the real 48-class
        # roster, and the old sample Rogue and Wizard collided with it.
        assert not hasattr(summary, "classes")
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


class TestDungeonMode:
    """Fills the real dungeon rather than inventing one (spec 025). The existing
    generator cannot show whether the actual progression graph, gates and class
    roster work, because it builds a world of its own."""

    async def test_it_creates_no_categories_skills_or_classes(
        self, db_session: AsyncSession
    ) -> None:
        before_categories = await _count(db_session, Category)
        before_skills = await _count(db_session, Skill)
        before_classes = await _count(db_session, CharacterClass)

        await sample_data.generate_dungeon(db_session)

        # It reads the seeded ones. Creating its own would defeat the purpose.
        assert await _count(db_session, Category) == before_categories
        assert await _count(db_session, Skill) == before_skills
        assert await _count(db_session, CharacterClass) == before_classes

    async def test_it_publishes_challenges_into_every_real_zone(
        self, db_session: AsyncSession
    ) -> None:
        summary = await sample_data.generate_dungeon(db_session)

        real_zones = (
            (
                await db_session.execute(
                    select(Category.id).where(~Category.slug.startswith(sample_data.SAMPLE_PREFIX))
                )
            )
            .scalars()
            .all()
        )
        filled = set(
            (
                await db_session.execute(
                    select(Challenge.category_id).where(
                        Challenge.slug.startswith(sample_data.SAMPLE_PREFIX)
                    )
                )
            )
            .scalars()
            .all()
        )

        assert summary.challenges > 0
        # Every zone in use is the whole goal — a dark zone shows nothing.
        assert set(real_zones) <= filled

    async def test_it_attaches_real_seeded_skills(self, db_session: AsyncSession) -> None:
        summary = await sample_data.generate_dungeon(db_session)

        attached = (
            (
                await db_session.execute(
                    select(ChallengeSkill.skill_id)
                    .join(Challenge, Challenge.id == ChallengeSkill.challenge_id)
                    .where(Challenge.slug.startswith(sample_data.SAMPLE_PREFIX))
                )
            )
            .scalars()
            .all()
        )
        real = set((await db_session.execute(select(Skill.id))).scalars().all())

        assert summary.skills > 0
        assert set(attached) <= real

    async def test_players_only_hold_solves_in_zones_they_could_open(
        self, db_session: AsyncSession
    ) -> None:
        await sample_data.generate_dungeon(db_session)

        # Every solve points at a published challenge in a real zone; nobody
        # carries a solve in a wing that was never filled.
        orphaned = (
            await db_session.execute(
                select(func.count(Solve.id))
                .join(Challenge, Challenge.id == Solve.challenge_id)
                .where(Challenge.state != ChallengeState.PUBLISHED)
            )
        ).scalar()

        assert orphaned == 0

    async def test_running_it_twice_replaces_rather_than_doubles(
        self, db_session: AsyncSession
    ) -> None:
        first = await sample_data.generate_dungeon(db_session)
        second = await sample_data.generate_dungeon(db_session)

        assert first.challenges == second.challenges


class TestPurgeLeavesRealContentAlone:
    async def test_it_keeps_the_real_categories_skills_and_classes(
        self, db_session: AsyncSession
    ) -> None:
        categories = await _count(db_session, Category)
        skills = await _count(db_session, Skill)
        classes = await _count(db_session, CharacterClass)

        await sample_data.generate_dungeon(db_session)
        await sample_data.purge(db_session)

        assert await _count(db_session, Category) == categories
        assert await _count(db_session, Skill) == skills
        assert await _count(db_session, CharacterClass) == classes

    async def test_a_players_chosen_class_survives_a_purge(self, db_session: AsyncSession) -> None:
        """The purge used to run DELETE ... WHERE name IN ('Rogue', 'Seer',
        'Wizard'). Once 024 seeded a real Rogue and Wizard that took two roster
        entries with it, and ON DELETE SET NULL returned their players to
        Classless."""
        rogue = (
            await db_session.execute(select(CharacterClass).where(CharacterClass.name == "Rogue"))
        ).scalar_one()
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        user.character_class_id = rogue.id
        await db_session.flush()

        await sample_data.generate(db_session)
        await sample_data.purge(db_session)
        await db_session.refresh(user)

        assert user.character_class_id == rogue.id
