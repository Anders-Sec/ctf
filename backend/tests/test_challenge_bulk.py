"""Bulk operations over selected challenges (spec 042)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.challenge import Category, Challenge, ChallengeState, Difficulty
from app.models.skill import ChallengeSkill, Skill
from app.models.user import UserRole, UserStatus
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def as_admin(db_session, client, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def bulk(client: AsyncClient, action: str, ids, value=None):
    return await client.post(
        "/api/admin/challenges/bulk",
        json={"challenge_ids": [str(i) for i in ids], "action": action, "value": value},
    )


class TestScalarActions:
    async def test_set_state_across_a_zone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The motivating case — a wing goes live as a unit."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        wing = [
            await make_challenge(
                db_session, category=category, title=f"Room {i}", state=ChallengeState.DRAFT
            )
            for i in range(3)
        ]
        bystander = await make_challenge(
            db_session, category=category, title="Elsewhere", state=ChallengeState.DRAFT
        )

        response = await bulk(client, "set_state", [c.id for c in wing], "published")

        assert response.status_code == 200
        assert response.json()["succeeded"] == 3
        await db_session.refresh(bystander)
        for challenge in wing:
            await db_session.refresh(challenge)
            assert challenge.state == ChallengeState.PUBLISHED
        assert bystander.state == ChallengeState.DRAFT

    async def test_set_difficulty_does_not_touch_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Spec 040 made difficulty a label. A bulk relabel that silently
        re-priced a zone would undo that."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(
            db_session,
            category=category,
            title="Relabelled",
            difficulty=Difficulty.EASY,
            initial_points=137,
        )

        await bulk(client, "set_difficulty", [challenge.id], "nearly_impossible")

        await db_session.refresh(challenge)
        assert challenge.difficulty == Difficulty.NEARLY_IMPOSSIBLE
        assert challenge.initial_points == 137

    async def test_absolute_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        a = await make_challenge(db_session, category=category, title="A", initial_points=100)
        b = await make_challenge(db_session, category=category, title="B", initial_points=400)

        await bulk(client, "set_xp", [a.id, b.id], "250")

        await db_session.refresh(a)
        await db_session.refresh(b)
        assert (a.initial_points, b.initial_points) == (250, 250)

    async def test_relative_xp_is_per_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The reason relative exists: an absolute value flattens a zone's whole
        spread to one number."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        a = await make_challenge(db_session, category=category, title="A", initial_points=100)
        b = await make_challenge(db_session, category=category, title="B", initial_points=400)

        await bulk(client, "set_xp", [a.id, b.id], "+25")

        await db_session.refresh(a)
        await db_session.refresh(b)
        assert (a.initial_points, b.initial_points) == (125, 425)

    async def test_percentage_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(
            db_session, category=category, title="Trimmed", initial_points=200
        )

        await bulk(client, "set_xp", [challenge.id], "-10%")

        await db_session.refresh(challenge)
        assert challenge.initial_points == 180

    async def test_xp_never_lands_below_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(
            db_session, category=category, title="Floored", initial_points=10
        )

        await bulk(client, "set_xp", [challenge.id], "-500")

        await db_session.refresh(challenge)
        assert challenge.initial_points == 1

    async def test_a_junk_value_is_refused_once(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A bad difficulty would fail identically on all 242. Reporting it 242
        times is noise, so it is refused up front."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Untouched")

        response = await bulk(client, "set_difficulty", [challenge.id], "impossibly_hard")

        assert response.status_code == 422
        await db_session.refresh(challenge)
        assert challenge.difficulty == Difficulty.MEDIUM


class TestSkills:
    async def test_adding_skills_is_additive(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Replace would be the same gesture with a silent wipe of every
        per-challenge mapping."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Skilled")
        existing = Skill(name="Already Here", category_id=category.id)
        shared = Skill(name="Applied In Bulk", category_id=category.id)
        db_session.add_all([existing, shared])
        await db_session.flush()
        db_session.add(ChallengeSkill(challenge_id=challenge.id, skill_id=existing.id))
        await db_session.flush()

        response = await bulk(client, "add_skills", [challenge.id], ["Applied In Bulk"])

        assert response.status_code == 200
        attached = set(
            (
                await db_session.execute(
                    select(ChallengeSkill.skill_id).where(
                        ChallengeSkill.challenge_id == challenge.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert attached == {existing.id, shared.id}

    async def test_adding_a_skill_twice_does_not_duplicate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Twice")
        skill = Skill(name="Applied Twice", category_id=category.id)
        db_session.add(skill)
        await db_session.flush()

        await bulk(client, "add_skills", [challenge.id], ["Applied Twice"])
        response = await bulk(client, "add_skills", [challenge.id], ["Applied Twice"])

        assert response.status_code == 200
        count = await db_session.scalar(
            select(func.count())
            .select_from(ChallengeSkill)
            .where(ChallengeSkill.challenge_id == challenge.id)
        )
        assert count == 1

    async def test_removing_skills(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Stripped")
        skill = Skill(name="To Be Removed", category_id=category.id)
        db_session.add(skill)
        await db_session.flush()
        db_session.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill.id))
        await db_session.flush()

        await bulk(client, "remove_skills", [challenge.id], ["To Be Removed"])

        count = await db_session.scalar(
            select(func.count())
            .select_from(ChallengeSkill)
            .where(ChallengeSkill.challenge_id == challenge.id)
        )
        assert count == 0

    async def test_an_unknown_skill_refuses_the_whole_operation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A typo would otherwise quietly apply to nothing, 242 times over."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Typo Victim")

        response = await bulk(client, "add_skills", [challenge.id], ["No Such Skill"])

        assert response.status_code == 422
        assert "No Such Skill" in response.text


class TestDelete:
    async def test_solved_challenges_are_skipped_not_fatal(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole reason this is per-item: refusing to remove two deletable
        challenges because a third has solves would be obstructive."""
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        keep = await make_challenge(db_session, category=category, title="Solved")
        gone = [
            await make_challenge(db_session, category=category, title=f"Unsolved {i}")
            for i in range(2)
        ]
        await record_solve(db_session, admin, keep)

        response = await bulk(client, "delete", [keep.id, *[c.id for c in gone]])

        body = response.json()
        assert body["succeeded"] == 2
        assert body["failed"] == 1
        blocked = next(r for r in body["results"] if not r["ok"])
        assert blocked["challenge_id"] == str(keep.id)
        assert "solved" in blocked["reason"].lower()
        remaining = (
            (
                await db_session.execute(
                    select(Challenge.title).where(Challenge.category_id == category.id)
                )
            )
            .scalars()
            .all()
        )
        assert list(remaining) == ["Solved"]

    async def test_emptying_a_zone_deletes_the_zone_and_says_so(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Spec 013 prunes an empty category. One at a time that is a tidy-up;
        in bulk it is invisible from the selection, so it is reported."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session, name="Doomed Zone")
        everything = [
            await make_challenge(db_session, category=category, title=f"Room {i}") for i in range(3)
        ]

        response = await bulk(client, "delete", [c.id for c in everything])

        assert response.json()["categories_deleted"] == ["Doomed Zone"]
        assert await db_session.get(Category, category.id) is None

    async def test_a_partly_deleted_zone_survives(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session, name="Surviving Zone")
        going = await make_challenge(db_session, category=category, title="Going")
        await make_challenge(db_session, category=category, title="Staying")

        response = await bulk(client, "delete", [going.id])

        assert response.json()["categories_deleted"] == []
        assert await db_session.get(Category, category.id) is not None

    async def test_preview_reports_the_blast_radius(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """What the confirm dialog says — neither fact is visible from the
        selection itself."""
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session, name="Previewed Zone")
        solved = await make_challenge(db_session, category=category, title="Solved")
        unsolved = await make_challenge(db_session, category=category, title="Unsolved")
        db_session.add(Skill(name="Orphan Candidate", category_id=category.id))
        await record_solve(db_session, admin, solved)
        await db_session.flush()

        response = await client.post(
            "/api/admin/challenges/bulk/preview-delete",
            json={
                "challenge_ids": [str(solved.id), str(unsolved.id)],
                "action": "delete",
            },
        )

        body = response.json()
        assert body["deletable"] == 1
        assert len(body["blocked"]) == 1
        # The zone survives: its solved challenge cannot be deleted, so it is
        # not actually emptied.
        assert body["zones_emptied"] == []

    async def test_preview_names_a_zone_that_would_go(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session, name="Fully Selected Zone")
        everything = [
            await make_challenge(db_session, category=category, title=f"Room {i}") for i in range(2)
        ]
        db_session.add(Skill(name="Would Be Orphaned", category_id=category.id))
        await db_session.flush()

        response = await client.post(
            "/api/admin/challenges/bulk/preview-delete",
            json={
                "challenge_ids": [str(c.id) for c in everything],
                "action": "delete",
            },
        )

        zones = response.json()["zones_emptied"]
        assert len(zones) == 1
        assert zones[0]["name"] == "Fully Selected Zone"
        assert zones[0]["skills_orphaned"] == 1


class TestGuards:
    async def test_one_audit_entry_per_operation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Not one per challenge — 242 rows for one decision would bury the log."""
        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenges = [
            await make_challenge(db_session, category=category, title=f"Row {i}") for i in range(5)
        ]

        await bulk(client, "set_state", [c.id for c in challenges], "hidden")

        entries = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.action == "challenge.bulk.set_state")
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].meta["succeeded"] == 5

    async def test_an_id_that_no_longer_exists_is_reported(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        real = await make_challenge(db_session, category=category, title="Real")

        body = (await bulk(client, "set_state", [real.id, uuid.uuid4()], "hidden")).json()

        assert body["succeeded"] == 1
        assert body["failed"] == 1

    async def test_too_many_ids_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await as_admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/challenges/bulk",
            json={
                "challenge_ids": [str(uuid.uuid4()) for _ in range(501)],
                "action": "set_state",
                "value": "hidden",
            },
        )

        assert response.status_code == 422

    async def test_a_player_may_not_bulk_edit(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, role=UserRole.PLAYER, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Protected")

        assert (await bulk(client, "delete", [challenge.id])).status_code == 403
