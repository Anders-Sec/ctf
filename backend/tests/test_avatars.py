"""Avatars, sigils and accessories (spec 073 §9)."""

import ast
import io
import pathlib

from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.avatar import AccessorySlot, AvatarAccessory, UnlockKind
from app.models.character_class import CharacterClass, Rarity
from app.models.notification import (
    Achievement,
    AchievementAward,
    LootBox,
    LootBoxType,
    LootRarity,
)
from app.models.user import AvatarSource, UserRole
from app.services import avatars
from app.services.accessory_roster import authored_roster, seed
from app.services.sigils import CHARGES, DIVISIONS, describe_sigil, render_sigil
from tests.factories import make_user

# --------------------------------------------------------------------------
# Sigils
# --------------------------------------------------------------------------


class TestSigils:
    def test_same_id_gives_the_same_bytes(self) -> None:
        # Served from several pods; a crest that differed per process would
        # change under a player as they refreshed.
        first = render_sigil("11111111-1111-1111-1111-111111111111", 128)
        second = render_sigil("11111111-1111-1111-1111-111111111111", 128)

        assert first == second

    def test_different_ids_give_different_crests(self) -> None:
        crests = {render_sigil(f"user-{index}", 64) for index in range(40)}

        # The whole reason this replaced a letter in a circle.
        assert len(crests) > 30

    def test_it_is_a_png_of_the_size_asked_for(self) -> None:
        image = Image.open(io.BytesIO(render_sigil("someone", 256)))

        assert image.format == "PNG"
        assert image.size == (256, 256)

    def test_every_charge_and_division_renders(self) -> None:
        # A charge that threw would only show up for the unlucky player whose
        # id happened to select it.
        from app.services.sigils import _digest

        seen_charges: set[str] = set()
        seen_divisions: set[str] = set()
        for index in range(600):
            user_id = f"probe-{index}"
            stream = _digest(user_id)
            seen_charges.add(CHARGES[stream[4] % len(CHARGES)])
            seen_divisions.add(DIVISIONS[stream[3] % len(DIVISIONS)])
            assert render_sigil(user_id, 48)

        assert seen_charges == set(CHARGES)
        assert seen_divisions == set(DIVISIONS)

    def test_the_description_reads_as_english(self) -> None:
        described = describe_sigil("11111111-1111-1111-1111-111111111111")

        assert described.startswith("A ")
        assert described.endswith(".")
        # "a argent" was in the first version.
        assert " a argent " not in described
        assert " a or " not in described


# --------------------------------------------------------------------------
# The authored roster
# --------------------------------------------------------------------------


class TestRoster:
    def _seeded_class_names(self) -> set[str]:
        source = pathlib.Path("migrations/versions/0027_seed_class_roster.py").read_text(
            encoding="utf-8"
        )
        block = source[source.index("ROSTER = [") :]
        block = block[: block.index("\n]\n") + 3]
        return {row[0] for row in ast.literal_eval(block.split("=", 1)[1].strip())}

    def _registered_achievement_codes(self) -> set[str]:
        import re

        source = pathlib.Path("app/services/achievements.py").read_text(encoding="utf-8")
        return set(re.findall(r'@trigger\("([a-z_0-9]+)"', source))

    def test_every_class_unlock_names_a_real_class(self) -> None:
        # The first draft invented a "Paladin", which is not one of the 48 — an
        # accessory nobody could ever earn, and nothing would have said so.
        names = self._seeded_class_names()
        refs = {
            item.unlock_ref for item in authored_roster() if item.unlock_kind == UnlockKind.CLASS
        }

        assert refs <= names, f"not in the class roster: {sorted(refs - names)}"

    def test_every_achievement_unlock_names_a_real_trigger(self) -> None:
        # Same mistake, same draft: "boss_first_kill" does not exist.
        codes = self._registered_achievement_codes()
        refs = {
            item.unlock_ref
            for item in authored_roster()
            if item.unlock_kind == UnlockKind.ACHIEVEMENT
        }

        assert refs <= codes, f"no such achievement: {sorted(refs - codes)}"

    def test_every_loot_unlock_names_a_real_rarity(self) -> None:
        rarities = {member.value for member in LootRarity}
        refs = {
            item.unlock_ref
            for item in authored_roster()
            if item.unlock_kind == UnlockKind.LOOT_RARITY
        }

        assert refs <= rarities, f"no such rarity: {sorted(refs - rarities)}"

    def test_slugs_are_unique(self) -> None:
        roster = authored_roster()

        assert len({item.slug for item in roster}) == len(roster)

    def test_only_always_unlocks_have_no_reference(self) -> None:
        for item in authored_roster():
            if item.unlock_kind == UnlockKind.ALWAYS:
                assert item.unlock_ref is None
            else:
                assert item.unlock_ref, f"{item.slug} has no unlock_ref"

    async def test_seeding_is_idempotent(self, db_session: AsyncSession) -> None:
        added = await seed(db_session)
        again = await seed(db_session)

        assert added > 0
        assert again == 0

    async def test_seeding_leaves_a_tuned_anchor_alone(self, db_session: AsyncSession) -> None:
        # An operator who nudged an anchor during setup must not have it
        # reverted by the next deploy.
        await seed(db_session)
        row = (
            await db_session.execute(
                select(AvatarAccessory).where(AvatarAccessory.slug == "spectacles")
            )
        ).scalar_one()
        row.anchor_y = 0.99
        await db_session.flush()

        await seed(db_session)
        await db_session.refresh(row)

        assert row.anchor_y == 0.99


# --------------------------------------------------------------------------
# Unlock derivation
# --------------------------------------------------------------------------


async def _accessory(
    db: AsyncSession,
    slug: str,
    *,
    kind: UnlockKind,
    ref: str | None = None,
    slot: AccessorySlot = AccessorySlot.HEAD,
) -> AvatarAccessory:
    row = AvatarAccessory(
        slug=slug,
        name=slug.replace("-", " ").title(),
        slot=slot,
        image_key=f"accessories/{slug}.png",
        rarity=Rarity.COMMON,
        unlock_kind=kind,
        unlock_ref=ref,
    )
    db.add(row)
    await db.flush()
    return row


class TestUnlocks:
    async def test_always_is_held_by_everybody(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "starter-hood", kind=UnlockKind.ALWAYS)

        assert "starter-hood" in await avatars.unlocked_slugs(db_session, user.id)

    async def test_a_class_piece_needs_that_class(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        wizard = CharacterClass(name="Test Wizard", rarity=Rarity.COMMON)
        other = CharacterClass(name="Test Rogue", rarity=Rarity.COMMON)
        db_session.add_all([wizard, other])
        await db_session.flush()
        await _accessory(db_session, "hat-wiz", kind=UnlockKind.CLASS, ref="Test Wizard")

        user.character_class_id = other.id
        await db_session.flush()
        assert "hat-wiz" not in await avatars.unlocked_slugs(db_session, user.id)

        user.character_class_id = wizard.id
        await db_session.flush()
        assert "hat-wiz" in await avatars.unlocked_slugs(db_session, user.id)

    async def test_class_matching_ignores_case(self, db_session: AsyncSession) -> None:
        # Class names are CITEXT and admin-editable; an unlock that broke on
        # capitalisation would be a very quiet bug.
        user = await make_user(db_session)
        klass = CharacterClass(name="Cipher Adept Test", rarity=Rarity.COMMON)
        db_session.add(klass)
        await db_session.flush()
        user.character_class_id = klass.id
        await _accessory(db_session, "hat-cipher", kind=UnlockKind.CLASS, ref="cipher adept test")
        await db_session.flush()

        assert "hat-cipher" in await avatars.unlocked_slugs(db_session, user.id)

    async def test_an_achievement_piece_needs_the_award(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        achievement = Achievement(
            code="test_crown_code",
            name=f"Test Crown {user.id.hex[:6]}",
            description="x",
            earned_by="x",
        )
        db_session.add(achievement)
        await db_session.flush()
        await _accessory(
            db_session, "crown-test", kind=UnlockKind.ACHIEVEMENT, ref="test_crown_code"
        )

        assert "crown-test" not in await avatars.unlocked_slugs(db_session, user.id)

        db_session.add(AchievementAward(achievement_id=achievement.id, user_id=user.id))
        await db_session.flush()

        assert "crown-test" in await avatars.unlocked_slugs(db_session, user.id)

    async def test_a_loot_piece_needs_a_box_of_that_rarity(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        achievement = Achievement(
            code=f"test_loot_{user.id.hex[:6]}",
            name=f"Test Loot {user.id.hex[:6]}",
            description="x",
            earned_by="x",
        )
        db_session.add(achievement)
        await db_session.flush()
        await _accessory(
            db_session,
            "frame-test-gold",
            kind=UnlockKind.LOOT_RARITY,
            ref="gold",
            slot=AccessorySlot.FRAME,
        )

        assert "frame-test-gold" not in await avatars.unlocked_slugs(db_session, user.id)

        db_session.add(
            LootBox(
                user_id=user.id,
                achievement_id=achievement.id,
                box_type=LootBoxType.ADVENTURER,
                rarity=LootRarity.GOLD,
            )
        )
        await db_session.flush()

        assert "frame-test-gold" in await avatars.unlocked_slugs(db_session, user.id)

    async def test_a_disabled_accessory_is_held_by_nobody(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        row = await _accessory(db_session, "pulled-hat", kind=UnlockKind.ALWAYS)
        row.enabled = False
        await db_session.flush()

        assert "pulled-hat" not in await avatars.unlocked_slugs(db_session, user.id)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


class TestRendering:
    async def test_the_same_recipe_gives_the_same_bytes(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)

        first = await avatars.render(db_session, user)
        second = await avatars.render(db_session, user)

        assert first == second

    async def test_a_sigil_user_still_renders(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)

        image = Image.open(io.BytesIO(await avatars.render(db_session, user)))

        assert image.size == (avatars.CANVAS, avatars.CANVAS)

    async def test_a_source_whose_bytes_are_gone_falls_back_to_a_crest(
        self, db_session: AsyncSession
    ) -> None:
        # Better a crest than a broken image.
        user = await make_user(db_session)
        user.avatar_source = AvatarSource.ENTRA
        user.avatar_base = None
        await db_session.flush()

        assert await avatars.render(db_session, user)

    async def test_a_malformed_config_renders_rather_than_raising(
        self, db_session: AsyncSession
    ) -> None:
        # Read on every roster row of the scoreboard; a 500 here is a 500 there.
        user = await make_user(db_session)
        user.avatar_config = {"layers": "not a list"}
        await db_session.flush()

        assert await avatars.render(db_session, user)

    async def test_an_accessory_that_vanished_does_not_break_the_avatar(
        self, db_session: AsyncSession
    ) -> None:
        user = await make_user(db_session)
        user.avatar_config = {"layers": [{"accessory": "no-such-thing"}]}
        await db_session.flush()

        assert await avatars.render(db_session, user)

    async def test_rendering_caches_into_the_blob(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        assert user.avatar_blob is None

        rendered = await avatars.rendered_for(db_session, user)

        assert user.avatar_blob == rendered

    async def test_invalidating_forces_a_re_render(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        await avatars.rendered_for(db_session, user)

        await avatars.invalidate(user)

        assert user.avatar_blob is None


class TestConfigParsing:
    def test_junk_entries_are_skipped_not_fatal(self) -> None:
        layers = avatars.layers_from_config(
            {"layers": [{"accessory": "hat"}, "nonsense", {"no": "slug"}, 7]}
        )

        assert [layer.accessory for layer in layers] == ["hat"]

    def test_defaults_fill_in_a_partial_layer(self) -> None:
        (layer,) = avatars.layers_from_config({"layers": [{"accessory": "hat"}]})

        assert (layer.x, layer.y, layer.scale, layer.rotation) == (0.5, 0.5, 1.0, 0.0)

    def test_a_round_trip_keeps_the_transform(self) -> None:
        original = [avatars.Layer("hat", 0.4, 0.2, 1.5, 15.0)]

        assert avatars.layers_from_config(avatars.config_from_layers(original)) == original


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


class TestApi:
    async def test_the_roster_marks_what_you_hold(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "api-starter", kind=UnlockKind.ALWAYS)
        await _accessory(db_session, "api-locked", kind=UnlockKind.CLASS, ref="Nobody Has This")
        await sign_in(client, user)

        response = await client.get("/api/avatar/accessories")

        assert response.status_code == 200
        by_slug = {row["slug"]: row for row in response.json()}
        assert by_slug["api-starter"]["unlocked"] is True
        # Listed, not withheld: seeing what there is to earn is the point.
        assert by_slug["api-locked"]["unlocked"] is False

    async def test_equipping_an_unlocked_accessory(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "api-hood", kind=UnlockKind.ALWAYS)
        await sign_in(client, user)

        response = await client.put(
            "/api/avatar/me",
            json={"source": "sigil", "layers": [{"accessory": "api-hood", "y": 0.3}]},
        )

        assert response.status_code == 200
        assert response.json()["layers"][0]["accessory"] == "api-hood"

    async def test_a_locked_accessory_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Refused rather than silently dropped: nobody should end up believing
        # they equipped something they did not.
        user = await make_user(db_session)
        await _accessory(db_session, "api-forbidden", kind=UnlockKind.CLASS, ref="Nobody Has This")
        await sign_in(client, user)

        response = await client.put(
            "/api/avatar/me",
            json={"source": "sigil", "layers": [{"accessory": "api-forbidden"}]},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "accessory_locked"

    async def test_two_things_cannot_share_a_slot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "api-hat-a", kind=UnlockKind.ALWAYS)
        await _accessory(db_session, "api-hat-b", kind=UnlockKind.ALWAYS)
        await sign_in(client, user)

        response = await client.put(
            "/api/avatar/me",
            json={
                "source": "sigil",
                "layers": [{"accessory": "api-hat-a"}, {"accessory": "api-hat-b"}],
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "duplicate_accessory_slot"

    async def test_an_unknown_accessory_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await sign_in(client, user)

        response = await client.put(
            "/api/avatar/me", json={"source": "sigil", "layers": [{"accessory": "nope"}]}
        )

        assert response.status_code == 404

    async def test_a_transform_off_the_canvas_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "api-band", kind=UnlockKind.ALWAYS)
        await sign_in(client, user)

        response = await client.put(
            "/api/avatar/me",
            json={"source": "sigil", "layers": [{"accessory": "api-band", "scale": 99}]},
        )

        assert response.status_code == 422

    async def test_asking_for_a_photo_there_is_none_of_gives_a_crest(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await sign_in(client, user)

        response = await client.put("/api/avatar/me", json={"source": "entra", "layers": []})

        assert response.status_code == 200
        assert response.json()["source"] == "sigil"

    async def test_reset_returns_to_the_bare_crest(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session)
        await _accessory(db_session, "api-reset-hood", kind=UnlockKind.ALWAYS)
        await sign_in(client, user)
        await client.put(
            "/api/avatar/me",
            json={"source": "sigil", "layers": [{"accessory": "api-reset-hood"}]},
        )

        response = await client.post("/api/avatar/me/reset")

        assert response.status_code == 200
        assert response.json()["layers"] == []

    async def test_the_avatar_endpoint_serves_a_png_for_everybody(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # There is no "no avatar" case any more, which is what let the frontend
        # drop its second rendering path.
        viewer = await make_user(db_session)
        subject = await make_user(db_session)
        await sign_in(client, viewer)

        response = await client.get(f"/api/users/{subject.id}/avatar")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(response.content)).format == "PNG"

    async def test_an_unchanged_avatar_costs_a_304(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        viewer = await make_user(db_session)
        subject = await make_user(db_session)
        await sign_in(client, viewer)
        first = await client.get(f"/api/users/{subject.id}/avatar")

        second = await client.get(
            f"/api/users/{subject.id}/avatar",
            headers={"If-None-Match": first.headers["etag"]},
        )

        assert second.status_code == 304

    async def test_reading_an_avatar_does_not_need_the_event_to_be_running(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Spec 068 found every character route 403-ing the moment the event
        # ended. An avatar is identity, not play.
        viewer = await make_user(db_session)
        await sign_in(client, viewer)

        assert (await client.get("/api/avatar/me")).status_code == 200
        assert (await client.get("/api/avatar/accessories")).status_code == 200


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------


class TestAdmin:
    async def test_the_roster_is_listed_for_staff(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN)
        await _accessory(db_session, "admin-listed", kind=UnlockKind.ALWAYS)
        await sign_in(client, admin)

        response = await client.get("/api/admin/avatar/accessories")

        assert response.status_code == 200
        assert any(row["slug"] == "admin-listed" for row in response.json())

    async def test_a_player_cannot_see_the_admin_roster(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session)
        await sign_in(client, player)

        assert (await client.get("/api/admin/avatar/accessories")).status_code == 403

    async def test_creating_an_accessory(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN)
        await sign_in(client, admin)

        response = await client.post(
            "/api/admin/avatar/accessories",
            json={"slug": "brand-new-hat", "name": "Brand New Hat", "slot": "head"},
        )

        assert response.status_code == 201
        assert response.json()["slug"] == "brand-new-hat"

    async def test_a_slug_has_to_be_kebab_case(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Configs name accessories by slug, so a slug is a stable key rather
        # than a label.
        admin = await make_user(db_session, role=UserRole.ADMIN)
        await sign_in(client, admin)

        response = await client.post(
            "/api/admin/avatar/accessories",
            json={"slug": "Not A Slug", "name": "x", "slot": "head"},
        )

        assert response.status_code == 422

    async def test_disabling_a_piece_takes_it_off_everybody(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN)
        row = await _accessory(db_session, "admin-pullable", kind=UnlockKind.ALWAYS)
        await sign_in(client, admin)

        response = await client.patch(
            f"/api/admin/avatar/accessories/{row.id}", json={"enabled": False}
        )

        assert response.status_code == 200
        assert "admin-pullable" not in await avatars.unlocked_slugs(db_session, admin.id)

    async def test_art_has_to_be_a_png(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # A JPEG has no alpha, so it would composite as an opaque square over
        # somebody's face rather than as a hat.
        admin = await make_user(db_session, role=UserRole.ADMIN)
        row = await _accessory(db_session, "admin-art", kind=UnlockKind.ALWAYS)
        await sign_in(client, admin)

        response = await client.post(
            f"/api/admin/avatar/accessories/{row.id}/art",
            files={"file": ("hat.jpg", b"\xff\xd8\xff not a png", "image/jpeg")},
        )

        assert response.status_code == 415

    async def test_reseeding_adds_what_is_missing_and_nothing_else(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN)
        await sign_in(client, admin)

        first = await client.post("/api/admin/avatar/accessories/reseed")
        second = await client.post("/api/admin/avatar/accessories/reseed")

        assert first.status_code == 200
        assert second.json()["message"] == "0 added."

    async def test_resetting_a_player_takes_the_portrait_with_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # A reset that left the offending image one click from being selected
        # again would not be a reset.
        admin = await make_user(db_session, role=UserRole.ADMIN)
        player = await make_user(db_session)
        player.avatar_source = AvatarSource.GENERATED
        player.avatar_base = b"pretend-portrait"
        player.avatar_config = {"layers": [{"accessory": "whatever"}]}
        await db_session.flush()
        await sign_in(client, admin)

        response = await client.post(f"/api/admin/avatar/users/{player.id}/reset")

        assert response.status_code == 200
        await db_session.refresh(player)
        assert player.avatar_source == AvatarSource.SIGIL
        assert player.avatar_base is None
        assert player.avatar_config == {}

    async def test_a_player_cannot_reset_somebody_else(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session)
        victim = await make_user(db_session)
        await sign_in(client, player)

        response = await client.post(f"/api/admin/avatar/users/{victim.id}/reset")

        assert response.status_code == 403
