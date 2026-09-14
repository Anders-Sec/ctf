"""The three achievements that needed somewhere to store their history (spec 039).

`you_broke_it`, `above_your_pay_grade` and `identity_crisis` were inert since 029
because the platform saw each of their events and forgot it. `player_event` is
what it remembers now.

Two of the three are written on a **failure** path, and that is the whole reason
`record_detached` exists: `get_db_session` rolls the request session back on any
exception, so a row added while raising a 403 — or while handling a 500 — would
be discarded with everything else. Those two are therefore tested at the seam,
by asserting the call, because a detached session cannot see rows the test has
not committed.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Authenticated
from app.models.character_class import CharacterClass, Rarity
from app.models.player_event import PlayerEventKind
from app.models.user import UserRole, UserStatus
from app.services import achievements as engine
from app.services import character as character_service
from app.services import player_events
from tests.factories import make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session):
    return await make_user(db_session, status=UserStatus.ACTIVE)


async def fires(db_session, code: str, user) -> bool:
    return await engine.REGISTRY[code].check(db_session, user.id)


async def record_many(db_session, user, kind: PlayerEventKind, count: int) -> None:
    for _ in range(count):
        await player_events.record(db_session, user.id, kind)
    await db_session.flush()


class TestRecordingAndCounting:
    async def test_a_recorded_event_can_be_counted_back(self, db_session: AsyncSession) -> None:
        user = await player(db_session)

        await record_many(db_session, user, PlayerEventKind.SERVER_ERROR, 3)

        assert await player_events.count(db_session, user.id, PlayerEventKind.SERVER_ERROR) == 3

    async def test_kinds_are_counted_separately(self, db_session: AsyncSession) -> None:
        user = await player(db_session)

        await record_many(db_session, user, PlayerEventKind.SERVER_ERROR, 2)
        await record_many(db_session, user, PlayerEventKind.CLASS_CHANGE, 5)

        assert await player_events.count(db_session, user.id, PlayerEventKind.SERVER_ERROR) == 2
        assert await player_events.count(db_session, user.id, PlayerEventKind.CLASS_CHANGE) == 5

    async def test_one_players_events_are_not_anothers(self, db_session: AsyncSession) -> None:
        breaker = await player(db_session)
        bystander = await player(db_session)

        await record_many(db_session, breaker, PlayerEventKind.SERVER_ERROR, 1)

        assert (
            await player_events.count(db_session, bystander.id, PlayerEventKind.SERVER_ERROR) == 0
        )


class TestTriggers:
    async def test_you_broke_it_needs_one_error(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        assert not await fires(db_session, "you_broke_it", user)

        await record_many(db_session, user, PlayerEventKind.SERVER_ERROR, 1)

        assert await fires(db_session, "you_broke_it", user)

    async def test_above_your_pay_grade_needs_one_closed_door(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        assert not await fires(db_session, "above_your_pay_grade", user)

        await record_many(db_session, user, PlayerEventKind.FORBIDDEN_ADMIN, 1)

        assert await fires(db_session, "above_your_pay_grade", user)

    async def test_identity_crisis_takes_ten_changes(self, db_session: AsyncSession) -> None:
        user = await player(db_session)

        await record_many(db_session, user, PlayerEventKind.CLASS_CHANGE, 9)
        assert not await fires(db_session, "identity_crisis", user)

        await record_many(db_session, user, PlayerEventKind.CLASS_CHANGE, 1)
        assert await fires(db_session, "identity_crisis", user)

    async def test_a_different_kind_does_not_satisfy_a_trigger(
        self, db_session: AsyncSession
    ) -> None:
        """Ten 500s is not an identity crisis, however it feels."""
        user = await player(db_session)

        await record_many(db_session, user, PlayerEventKind.SERVER_ERROR, 10)

        assert not await fires(db_session, "identity_crisis", user)


async def make_class(db_session, name: str) -> CharacterClass:
    character_class = CharacterClass(name=name, rarity=Rarity.COMMON)
    db_session.add(character_class)
    await db_session.flush()
    return character_class


async def classed_player(db_session, first: CharacterClass):
    """A player who already holds a class, so the unlock gate is behind them.

    `set_class` only checks the level for a *first* choice, and the gate is not
    what these tests are about.
    """
    user = await player(db_session)
    user.character_class_id = first.id
    await db_session.flush()
    return user


class TestClassChanges:
    async def test_changing_class_records_it(self, db_session: AsyncSession) -> None:
        first = await make_class(db_session, "Breaker")
        second = await make_class(db_session, "Mapper")
        user = await classed_player(db_session, first)

        await character_service.set_class(db_session, user, second.id)

        assert await player_events.count(db_session, user.id, PlayerEventKind.CLASS_CHANGE) == 1

    async def test_reselecting_the_same_class_is_not_a_change(
        self, db_session: AsyncSession
    ) -> None:
        """Ten clicks on the class already worn is not an identity crisis."""
        only = await make_class(db_session, "Breaker")
        user = await classed_player(db_session, only)

        for _ in range(10):
            await character_service.set_class(db_session, user, only.id)

        assert await player_events.count(db_session, user.id, PlayerEventKind.CLASS_CHANGE) == 0
        assert not await fires(db_session, "identity_crisis", user)

    async def test_clearing_a_class_is_a_change(self, db_session: AsyncSession) -> None:
        only = await make_class(db_session, "Breaker")
        user = await classed_player(db_session, only)

        await character_service.set_class(db_session, user, None)

        assert await player_events.count(db_session, user.id, PlayerEventKind.CLASS_CHANGE) == 1


@pytest.fixture
def recorded(monkeypatch) -> list[tuple]:
    """Capture detached writes.

    They run in a session of their own, against rows this test has not
    committed, so the seam is the only place they can be observed.
    """
    calls: list[tuple] = []

    async def _fake(user_id, kind) -> None:
        calls.append((user_id, kind))

    monkeypatch.setattr(player_events, "record_detached", _fake)
    return calls


class TestForbiddenAdmin:
    async def test_a_player_turned_away_by_the_admin_gate_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, recorded: list[tuple]
    ) -> None:
        user = await make_user(db_session, role=UserRole.PLAYER, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.post("/api/admin/users/approve", json={"user_ids": []})

        assert response.status_code == 403
        assert recorded == [(user.id, PlayerEventKind.FORBIDDEN_ADMIN)]

    async def test_a_player_turned_away_by_the_staff_gate_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, recorded: list[tuple]
    ) -> None:
        """The admin page a player would actually click is read through require_staff.

        Keying this on require_admin alone meant the achievement almost never
        fired — found live, not in a test.
        """
        user = await make_user(db_session, role=UserRole.PLAYER, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.get("/api/admin/users")

        assert response.status_code == 403
        assert recorded == [(user.id, PlayerEventKind.FORBIDDEN_ADMIN)]

    async def test_an_organizer_refused_a_destructive_action_is_not_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, recorded: list[tuple]
    ) -> None:
        """Staff doing their job, not a player rattling a handle."""
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        response = await client.post("/api/admin/users/approve", json={"user_ids": []})

        assert response.status_code == 403
        assert recorded == []

    async def test_an_admin_getting_through_records_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, recorded: list[tuple]
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)

        await client.get("/api/admin/users")

        assert recorded == []

    async def test_an_anonymous_caller_records_nothing(
        self, client: AsyncClient, recorded: list[tuple]
    ) -> None:
        """A 401 has no player to credit — nobody was turned away, they were not there."""
        response = await client.get("/api/admin/users")

        assert response.status_code == 401
        assert recorded == []


def boom_route(app: FastAPI) -> None:
    """A route that authenticates and then explodes.

    The dependency matters: attribution comes from `request.state.user_id`,
    which `require_authenticated` stamps. A 500 raised on a route that never
    identifies the caller has nobody to credit — see the open route below.
    """

    @app.get("/api/test/boom-039")
    async def _boom(current: Authenticated) -> None:
        raise RuntimeError("deliberate")


def open_boom_route(app: FastAPI) -> None:
    @app.get("/api/test/boom-039-open")
    async def _boom_open() -> None:
        raise RuntimeError("deliberate")


async def call_boom(app: FastAPI, cookies=None, path: str = "/api/test/boom-039") -> int:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as caller:
        if cookies is not None:
            caller.cookies = cookies
        return (await caller.get(path)).status_code


class TestServerError:
    async def test_a_500_is_credited_to_whoever_caused_it(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        recorded: list[tuple],
    ) -> None:
        user = await player(db_session)
        await sign_in(client, user)
        boom_route(app)

        assert await call_boom(app, client.cookies) == 500
        assert recorded == [(user.id, PlayerEventKind.SERVER_ERROR)]

    async def test_an_anonymous_500_credits_nobody(
        self, app: FastAPI, recorded: list[tuple]
    ) -> None:
        open_boom_route(app)

        assert await call_boom(app, path="/api/test/boom-039-open") == 500
        assert recorded == []

    async def test_a_signed_in_player_breaking_an_open_route_credits_nobody(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in, recorded
    ) -> None:
        """The limit of this design, stated rather than discovered later.

        Attribution rides on the authentication dependency, so a 500 raised
        somewhere that never identifies the caller is not credited — even when
        the caller was signed in. Every route a player can actually reach does
        authenticate, so this costs nothing real.
        """
        await sign_in(client, await player(db_session))
        open_boom_route(app)

        assert await call_boom(app, client.cookies, "/api/test/boom-039-open") == 500
        assert recorded == []

    async def test_a_failure_while_recording_does_not_change_the_response(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in, monkeypatch
    ) -> None:
        """A 500 raised while recording a 500 is strictly worse than a lost row."""
        user = await player(db_session)
        await sign_in(client, user)
        boom_route(app)

        async def _explode(user_id, kind) -> None:
            raise RuntimeError("the recorder is broken too")

        monkeypatch.setattr(player_events, "record_detached", _explode)

        assert await call_boom(app, client.cookies) == 500


class TestTheRosterIsFullyWired:
    async def test_nothing_in_the_roster_is_inert(self, db_session: AsyncSession) -> None:
        """The three above were the last of them (spec 039)."""
        from sqlalchemy import select

        from app.models.notification import Achievement

        codes = (await db_session.execute(select(Achievement.code))).scalars().all()
        inert = [code for code in codes if engine.resolve(code) is None]

        assert inert == []

    async def test_the_seven_non_monotone_achievements_are_gone(
        self, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from app.models.notification import Achievement

        codes = set((await db_session.execute(select(Achievement.code))).scalars().all())

        assert not codes & {
            "no_help_needed",
            "unassisted",
            "low_hanging_fruit",
            "vampire",
            "undefined",
            "wide_not_deep",
            "proud",
        }
