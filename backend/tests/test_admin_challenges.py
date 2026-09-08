"""Admin challenge management and artifact storage (spec 003).

Artifact tests run against the real MinIO from docker-compose, not a fake — the
whole point of the object store is that it behaves the same for every API
replica, and a stub would not exercise that.
"""

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.audit import AuditLog
from app.models.challenge import ChallengeState, MatchType
from app.models.user import UserRole, UserStatus
from app.services.artifacts import safe_filename, storage_key
from app.services.storage import S3ArtifactStorage, get_storage
from tests.factories import make_category, make_challenge, make_user, record_solve


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestAccessControl:
    async def test_a_player_cannot_read_the_challenge_admin(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/challenges")).status_code == 403

    async def test_an_organizer_can_read_but_not_write(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Staff checking a challenge must not be able to rewrite it."""
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)
        category = await make_category(db_session)

        assert (await client.get("/api/admin/challenges")).status_code == 200
        response = await client.post(
            "/api/admin/challenges",
            json={"title": "Nope", "slug": "nope", "category": category.name},
        )
        assert response.status_code == 403

    async def test_staff_see_drafts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)
        await make_challenge(db_session, title="Work In Progress", state=ChallengeState.DRAFT)

        titles = [c["title"] for c in (await client.get("/api/admin/challenges")).json()]

        assert "Work In Progress" in titles


class TestChallengeCrud:
    async def test_a_challenge_can_be_created(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)

        response = await client.post(
            "/api/admin/challenges",
            json={
                "title": "Packet Puzzle",
                "slug": "packet-puzzle",
                "category": category.name,
                "body": "Find the flag in the pcap.",
                "difficulty": "hard",
            },
        )

        assert response.status_code == 201
        body = response.json()
        # Drafts by default: a challenge must not go live the moment it is made.
        assert body["state"] == "draft"
        # Hard is modifier 20 against an XP base of 10 (spec 018).
        assert body["current_value"] == 200

    async def test_slugs_are_unique(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)
        payload = {"title": "First", "slug": "taken", "category": category.name}

        await client.post("/api/admin/challenges", json=payload)
        second = await client.post("/api/admin/challenges", json={**payload, "title": "Second"})

        assert second.status_code == 409
        assert second.json()["error"]["code"] == "slug_taken"

    async def test_an_impossible_decay_threshold_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The curve divides by it."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)

        response = await client.post(
            "/api/admin/challenges",
            json={
                "title": "Bad",
                "slug": "bad-curve",
                "category": category.name,
                "decay_threshold": 1,
            },
        )

        assert response.status_code == 422

    async def test_difficulty_derives_the_value_and_the_scoring_mode(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Points are no longer typed, so an inverted range is unreachable by
        construction (spec 018). Decay is on for the tie-breaker tiers only."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)

        easy = await client.post(
            "/api/admin/challenges",
            json={
                "title": "Gentle",
                "slug": "gentle",
                "category": category.name,
                "difficulty": "very_easy",
            },
        )
        brutal = await client.post(
            "/api/admin/challenges",
            json={
                "title": "Brutal",
                "slug": "brutal",
                "category": category.name,
                "difficulty": "nearly_impossible",
            },
        )

        assert easy.json()["current_value"] == 50
        assert easy.json()["scoring"] == "static"
        assert brutal.json()["current_value"] == 500
        assert brutal.json()["scoring"] == "dynamic"

    async def test_changing_difficulty_rederives_the_value(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)
        created = await client.post(
            "/api/admin/challenges",
            json={
                "title": "Shifting",
                "slug": "shifting",
                "category": category.name,
                "difficulty": "easy",
            },
        )
        assert created.json()["current_value"] == 100

        updated = await client.patch(
            f"/api/admin/challenges/{created.json()['id']}",
            json={"difficulty": "very_hard"},
        )

        assert updated.json()["current_value"] == 250
        assert updated.json()["scoring"] == "dynamic"

    async def test_publishing_is_instant(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session, state=ChallengeState.DRAFT)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/state", json={"state": "published"}
        )

        assert response.status_code == 200
        await db_session.refresh(challenge)
        assert challenge.state == ChallengeState.PUBLISHED

    async def test_hiding_a_challenge_leaves_its_solves_alone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """History is not rewritten because a challenge turned out to be broken."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        solver = await make_user(db_session)
        await record_solve(db_session, solver, challenge)

        await client.post(
            f"/api/admin/challenges/{challenge.id}/state",
            json={"state": "hidden", "reason": "Broken, being fixed"},
        )

        from app.services.scoring import user_score

        assert await user_score(db_session, solver.id) > 0

    async def test_a_solved_challenge_cannot_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Deleting it would erase points people earned."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        await record_solve(db_session, await make_user(db_session), challenge)

        response = await client.delete(f"/api/admin/challenges/{challenge.id}")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "challenge_has_solves"

    async def test_an_unsolved_challenge_can_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        assert (await client.delete(f"/api/admin/challenges/{challenge.id}")).status_code == 200

    async def test_changes_are_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session, state=ChallengeState.DRAFT)

        await client.post(
            f"/api/admin/challenges/{challenge.id}/state",
            json={"state": "published", "reason": "Ready to go"},
        )

        entry = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "challenge.set_state", AuditLog.target_id == challenge.id
                )
            )
        ).scalar_one()
        assert entry.actor_user_id == admin.id
        assert entry.meta == {"from": "draft", "to": "published"}
        assert entry.reason == "Ready to go"


class TestAnswerRules:
    async def test_a_rule_can_be_added(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/answers",
            json={"match_type": "regex", "value": r"flag\{\w+\}", "label": "any word"},
        )

        assert response.status_code == 201
        assert response.json()["match_type"] == "regex"

    async def test_a_broken_pattern_is_refused_at_save_time(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Rather than silently rejecting every correct answer during the event."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/answers",
            json={"match_type": "regex", "value": "(unclosed"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_answer_rule"

    async def test_the_answer_value_is_not_written_to_the_audit_log(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Organizers can read the audit log; it is not a place to broadcast answers."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        await client.post(
            f"/api/admin/challenges/{challenge.id}/answers",
            json={"match_type": "exact", "value": "flag{super-secret}"},
        )

        entry = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "challenge.answer_add")
            )
        ).scalar_one()
        assert "super-secret" not in str(entry.meta)

    async def test_an_admin_can_dry_run_a_candidate_answer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Authoring a regex blind and finding out mid-event is how challenges break."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(
            db_session, answers=[(MatchType.REGEX, r"flag\{[0-9a-f]{4}\}")]
        )

        good = await client.post(
            f"/api/admin/challenges/{challenge.id}/answers/test",
            json={"candidate": "flag{beef}"},
        )
        bad = await client.post(
            f"/api/admin/challenges/{challenge.id}/answers/test",
            json={"candidate": "flag{zzzz}"},
        )

        assert good.json()["correct"] is True
        assert bad.json()["correct"] is False

    async def test_the_dry_run_records_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.play import Submission

        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        await client.post(
            f"/api/admin/challenges/{challenge.id}/answers/test",
            json={"candidate": "flag{correct}"},
        )

        rows = (
            (await db_session.execute(select(Submission).where(Submission.user_id == admin.id)))
            .scalars()
            .all()
        )
        assert rows == []

    async def test_an_admin_sees_the_expected_answers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Someone has to be able to debug a challenge nobody is solving."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(
            db_session, answers=[(MatchType.EXACT, "flag{visible-to-admin}")]
        )

        body = (await client.get(f"/api/admin/challenges/{challenge.id}")).json()

        assert body["answers"][0]["value"] == "flag{visible-to-admin}"


class TestFilenameSafety:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("handout.zip", "handout.zip"),
            ("../../etc/passwd", "etc_passwd"),
            ("a b c.txt", "a_b_c.txt"),
            ("...", "artifact"),
            ("", "artifact"),
        ],
    )
    def test_names_are_reduced_to_something_safe(self, raw: str, expected: str) -> None:
        """The name reaches a Content-Disposition header and a player's disk."""
        assert safe_filename(raw) == expected

    def test_keys_are_namespaced_and_unique(self) -> None:
        """Two challenges may both ship handout.zip, and re-uploads must not clobber."""
        challenge_id = uuid.uuid4()

        first = storage_key(challenge_id, "handout.zip")
        second = storage_key(challenge_id, "handout.zip")

        assert first != second
        assert first.startswith(f"challenges/{challenge_id}/")


class TestArtifacts:
    """Against the real MinIO. Skipped when it is not running."""

    @pytest.fixture(autouse=True)
    async def _require_storage(self, settings: Settings):
        storage = get_storage(settings)
        if isinstance(storage, S3ArtifactStorage):
            await storage.ensure_bucket()
        if not await storage.healthy():
            pytest.skip("object storage is not available")

    async def test_an_artifact_round_trips_through_storage(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        payload = b"PK\x03\x04 pretend this is a zip"

        upload = await client.post(
            f"/api/admin/challenges/{challenge.id}/artifacts",
            files={"file": ("handout.zip", payload, "application/zip")},
        )

        assert upload.status_code == 201
        artifact = upload.json()
        assert artifact["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
        assert artifact["size_bytes"] == len(payload)

        download = await client.get(f"/api/challenges/{challenge.id}/artifacts/{artifact['id']}")

        assert download.status_code == 200
        assert download.content == payload
        assert "handout.zip" in download.headers["content-disposition"]
        assert admin.id is not None

    async def test_a_locked_challenges_files_are_unreachable(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        """A valid artifact id must not be a way past the lock."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        upload = await client.post(
            f"/api/admin/challenges/{challenge.id}/artifacts",
            files={"file": ("secret.bin", b"contents", "application/octet-stream")},
        )
        artifact_id = upload.json()["id"]

        challenge.state = ChallengeState.LOCKED
        await db_session.flush()
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        response = await client.get(f"/api/challenges/{challenge.id}/artifacts/{artifact_id}")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_an_artifact_id_from_another_challenge_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        owner = await make_challenge(db_session)
        other = await make_challenge(db_session)
        upload = await client.post(
            f"/api/admin/challenges/{owner.id}/artifacts",
            files={"file": ("f.bin", b"contents", "application/octet-stream")},
        )

        response = await client.get(f"/api/challenges/{other.id}/artifacts/{upload.json()['id']}")

        assert response.status_code == 404

    async def test_an_empty_upload_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/artifacts",
            files={"file": ("empty.bin", b"", "application/octet-stream")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "artifact_empty"

    async def test_an_oversized_upload_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, app, settings: Settings
    ) -> None:
        app.state.settings = settings.model_copy(update={"max_artifact_bytes": 16})
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/artifacts",
            files={"file": ("big.bin", b"x" * 64, "application/octet-stream")},
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "artifact_too_large"


class TestDerivedCategories:
    """Categories are typed on the challenge form and live only while a challenge
    is in them (spec 013)."""

    async def _create(self, client: AsyncClient, category: str, slug: str = "c") -> dict:
        response = await client.post(
            "/api/admin/challenges",
            json={"title": f"Ch {slug}", "slug": slug, "category": category},
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_a_new_name_creates_the_category(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        body = await self._create(client, "Web Exploitation", "web-1")

        assert body["category"]["name"] == "Web Exploitation"
        assert body["category"]["slug"] == "web-exploitation"

    async def test_an_existing_name_is_reused_regardless_of_case(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """One category, not three, whatever the capitalisation — CITEXT enforces it."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        first = await self._create(client, "Forensics", "f-1")
        second = await self._create(client, "forensics", "f-2")
        third = await self._create(client, "FORENSICS", "f-3")

        ids = {first["category"]["id"], second["category"]["id"], third["category"]["id"]}
        assert len(ids) == 1
        # The canonical spelling is the one first created.
        assert second["category"]["name"] == "Forensics"

    async def test_deleting_the_last_challenge_removes_the_category(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.challenge import Category

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        created = await self._create(client, "Lonely", "lonely-1")
        category_id = created["category"]["id"]

        deleted = await client.delete(f"/api/admin/challenges/{created['id']}")
        assert deleted.status_code == 200

        assert await db_session.get(Category, uuid.UUID(category_id)) is None

    async def test_a_category_with_other_challenges_survives(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.challenge import Category

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        first = await self._create(client, "Crypto", "crypto-1")
        second = await self._create(client, "Crypto", "crypto-2")
        category_id = first["category"]["id"]

        await client.delete(f"/api/admin/challenges/{first['id']}")

        # The second challenge keeps the category alive.
        assert await db_session.get(Category, uuid.UUID(category_id)) is not None
        assert second["category"]["id"] == category_id

    async def test_moving_a_challenge_prunes_the_emptied_category(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.challenge import Category

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        created = await self._create(client, "Misc", "misc-1")
        old_category_id = created["category"]["id"]

        moved = await client.patch(
            f"/api/admin/challenges/{created['id']}", json={"category": "Pwn"}
        )
        assert moved.status_code == 200
        assert moved.json()["category"]["name"] == "Pwn"

        # "Misc" is now empty and gone.
        assert await db_session.get(Category, uuid.UUID(old_category_id)) is None


class TestContainerAssignment:
    async def test_a_template_can_be_attached_and_detached(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from tests.factories import make_template

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        template = await make_template(db_session)
        created = await client.post(
            "/api/admin/challenges",
            json={"title": "Boxed", "slug": "boxed", "category": "Web"},
        )
        challenge_id = created.json()["id"]

        attached = await client.patch(
            f"/api/admin/challenges/{challenge_id}",
            json={"container_template_id": str(template.id)},
        )
        assert attached.status_code == 200
        assert attached.json()["container_template_id"] == str(template.id)

        detached = await client.patch(
            f"/api/admin/challenges/{challenge_id}", json={"container_template_id": None}
        )
        assert detached.json()["container_template_id"] is None

    async def test_an_unknown_template_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        created = await client.post(
            "/api/admin/challenges",
            json={"title": "Boxed2", "slug": "boxed2", "category": "Web"},
        )
        response = await client.patch(
            f"/api/admin/challenges/{created.json()['id']}",
            json={"container_template_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
