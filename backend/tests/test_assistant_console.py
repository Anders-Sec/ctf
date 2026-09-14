"""The System AI admin console (spec 034).

Three things this has to get right: the aggregates are honest, the transcript is
admin-only and audited, and the scratchpad appears here and nowhere else.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.audit import AuditLog
from app.models.guardrail import (
    AssistantFinding,
    FindingAction,
    GuardrailLayer,
    Severity,
)
from app.models.user import User, UserRole, UserStatus
from app.services import assistant_metrics as metrics
from tests.factories import make_ladder, make_user, record_solve

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("running_event")]


async def _conversation(db: AsyncSession, user: User) -> AssistantConversation:
    conversation = AssistantConversation(user_id=user.id, message_count=0)
    db.add(conversation)
    await db.flush()
    return conversation


async def _turn(
    db: AsyncSession,
    conversation: AssistantConversation,
    *,
    level: int = 0,
    trace: list[str] | None = None,
    latency_ms: int | None = 100,
    calls: int | None = 1,
    error: str | None = None,
    withheld: bool = False,
    from_staff: bool = False,
    reasoning: str | None = None,
    minutes_ago: int = 0,
    content: str = "A reply.",
) -> AssistantMessage:
    """One assistant turn. The metrics only count this half."""
    created = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    message = AssistantMessage(
        conversation_id=conversation.id,
        sequence=conversation.message_count,
        role=MessageRole.ASSISTANT,
        content=content,
        original_content="the withheld text" if withheld else None,
        reasoning_content=reasoning,
        ladder_level=level,
        trace=trace,
        latency_ms=latency_ms,
        upstream_calls=calls,
        error=error,
        from_staff=from_staff,
        created_at=created,
    )
    db.add(message)
    conversation.message_count += 1
    conversation.last_message_at = created
    await db.flush()
    return message


async def _finding(
    db: AsyncSession, user: User, message: AssistantMessage, *, rule: str = "malware_build"
) -> AssistantFinding:
    finding = AssistantFinding(
        message_id=message.id,
        user_id=user.id,
        layer=GuardrailLayer.SAFETY,
        rule=rule,
        severity=Severity.HIGH,
        action=FindingAction.DEFLECTED,
        detail={},
        from_staff=False,
    )
    db.add(finding)
    await db.flush()
    return finding


async def _as(db, client, sign_in, role: UserRole) -> User:
    user = await make_user(db, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestMetrics:
    async def test_windows_count_only_recent_turns(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, minutes_ago=1)
        await _turn(db_session, conversation, minutes_ago=10)
        await _turn(db_session, conversation, minutes_ago=90)

        result = await metrics.collect(db_session)

        assert result.windows["5m"].turns == 1
        assert result.windows["15m"].turns == 2
        assert result.windows["60m"].turns == 2
        assert result.total_turns == 3

    async def test_staff_turns_are_excluded(self, db_session: AsyncSession) -> None:
        """Our own testing should not move the numbers staff read to decide things."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation)
        await _turn(db_session, conversation, from_staff=True)

        assert (await metrics.collect(db_session)).windows["5m"].turns == 1
        assert (await metrics.collect(db_session, include_staff=True)).windows["5m"].turns == 2

    async def test_latency_percentiles(self, db_session: AsyncSession) -> None:
        """The average hides the tail, and the tail is what players feel."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        for latency in (100, 200, 300, 400, 5000):
            await _turn(db_session, conversation, latency_ms=latency)

        window = (await metrics.collect(db_session)).windows["5m"]

        assert window.median_latency_ms == 300
        assert window.p95_latency_ms > 400

    async def test_a_single_turn_has_a_percentile(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, latency_ms=250)

        window = (await metrics.collect(db_session)).windows["5m"]

        assert window.median_latency_ms == 250
        assert window.p95_latency_ms == 250

    async def test_no_traffic_reports_nothing_rather_than_zero_latency(
        self, db_session: AsyncSession
    ) -> None:
        window = (await metrics.collect(db_session)).windows["5m"]

        assert window.turns == 0
        assert window.median_latency_ms is None
        assert window.calls_per_turn is None

    async def test_calls_per_turn_is_the_capacity_figure(self, db_session: AsyncSession) -> None:
        """A level 5 turn costs five, and each takes one of eight in-flight slots."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, level=0, calls=1)
        await _turn(db_session, conversation, level=5, calls=5)

        window = (await metrics.collect(db_session)).windows["5m"]

        assert window.upstream_calls == 6
        assert window.calls_per_turn == 3.0

    async def test_errors_are_broken_down_by_reason(self, db_session: AsyncSession) -> None:
        """`timeout` and `breaker_open` mean different things to do about them."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, error="timeout")
        await _turn(db_session, conversation, error="timeout")
        await _turn(db_session, conversation, error="breaker_open")

        result = await metrics.collect(db_session)

        assert result.errors_by_reason == {"timeout": 2, "breaker_open": 1}
        assert result.windows["5m"].errors == 3

    async def test_deflections_are_counted(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, withheld=True)
        await _turn(db_session, conversation)

        assert (await metrics.collect(db_session)).windows["5m"].deflections == 1


class TestRungs:
    async def test_gate_fires_are_counted_per_rung(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, level=4, trace=["router"])
        await _turn(db_session, conversation, level=4, trace=["router"])
        await _turn(db_session, conversation, level=3, trace=["warden"])

        rungs = {r.level: r for r in (await metrics.collect(db_session)).rungs}

        assert rungs[4].gates["router"] == 2
        assert rungs[3].gates["warden"] == 1
        assert rungs[4].turns == 2

    async def test_a_turn_with_several_gates_counts_each(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, level=5, trace=["vault:ARCHIVE-6", "warden"])

        rungs = {r.level: r for r in (await metrics.collect(db_session)).rungs}

        assert rungs[5].gates["warden"] == 1
        # A vault lookup is not a gate; it should not be counted as one.
        assert "vault" not in rungs[5].gates

    async def test_solves_and_decoys_are_separated(self, db_session: AsyncSession) -> None:
        """Decoys must stay near zero: a climb means the model has started
        inventing flags players are about to submit."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, level=0, trace=["SOLVED"])
        await _turn(db_session, conversation, level=0, trace=["decoy-filter"])

        rungs = {r.level: r for r in (await metrics.collect(db_session)).rungs}

        assert rungs[0].solves == 1
        assert rungs[0].decoys == 1

    async def test_the_input_filter_word_is_not_a_separate_gate(
        self, db_session: AsyncSession
    ) -> None:
        """The trace carries the matched word: "input-filter:flag"."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, user)
        await _turn(db_session, conversation, level=2, trace=["input-filter:flag"])
        await _turn(db_session, conversation, level=2, trace=["input-filter:secret"])

        rungs = {r.level: r for r in (await metrics.collect(db_session)).rungs}

        assert rungs[2].gates["input-filter"] == 2

    async def test_players_are_counted_per_rung(self, db_session: AsyncSession) -> None:
        ladder = await make_ladder(db_session)
        climber = await make_user(db_session, status=UserStatus.ACTIVE)
        beginner = await make_user(db_session, status=UserStatus.ACTIVE)
        for challenge in ladder[:2]:
            await record_solve(db_session, climber, challenge)
        await record_solve(db_session, beginner, ladder[0])

        rungs = {r.level: r for r in (await metrics.collect(db_session)).rungs}

        assert rungs[2].players == 1
        assert rungs[1].players == 1

    async def test_every_rung_appears_even_with_no_traffic(self, db_session: AsyncSession) -> None:
        rungs = (await metrics.collect(db_session)).rungs

        assert [r.level for r in rungs] == [0, 1, 2, 3, 4, 5]
        assert rungs[0].name == "Very Easy"


class TestAcknowledgement:
    async def test_a_finding_can_be_marked_as_seen(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        message = await _turn(db_session, conversation)
        finding = await _finding(db_session, player, message)
        staff = await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        response = await client.post(f"/api/admin/assistant/findings/{finding.id}/acknowledge")

        assert response.status_code == 200
        await db_session.refresh(finding)
        assert finding.acknowledged_at is not None
        assert finding.acknowledged_by_user_id == staff.id

    async def test_the_unreviewed_filter_hides_it_afterwards(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Without this the screen shows the same rows on every refresh."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        message = await _turn(db_session, conversation)
        finding = await _finding(db_session, player, message)
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        before = (await client.get("/api/admin/assistant/findings?unreviewed=true")).json()
        await client.post(f"/api/admin/assistant/findings/{finding.id}/acknowledge")
        after = (await client.get("/api/admin/assistant/findings?unreviewed=true")).json()

        assert before["total"] == 1
        assert after["total"] == 0

    async def test_an_unknown_finding_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        response = await client.post(f"/api/admin/assistant/findings/{uuid.uuid4()}/acknowledge")

        assert response.status_code == 404

    async def test_findings_filter_by_rule(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        message = await _turn(db_session, conversation)
        await _finding(db_session, player, message, rule="malware_build")
        await _finding(db_session, player, message, rule="real_world_target")
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        body = (await client.get("/api/admin/assistant/findings?rule=malware_build")).json()

        assert body["total"] == 1


class TestSessions:
    async def test_the_list_carries_no_message_content(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Reading a colleague's messages should be a decision, not a side effect
        of glancing at a page."""
        player = await make_user(db_session, status=UserStatus.ACTIVE, display_name="Mira")
        conversation = await _conversation(db_session, player)
        await _turn(db_session, conversation, content="something private")
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        response = await client.get("/api/admin/assistant/sessions")

        assert response.status_code == 200
        assert "something private" not in response.text
        assert response.json()["sessions"][0]["player_name"] == "Mira"

    async def test_only_recently_active_sessions_by_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        quiet = await make_user(db_session, status=UserStatus.ACTIVE, display_name="Quiet")
        stale = await _conversation(db_session, quiet)
        await _turn(db_session, stale, minutes_ago=120)
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        recent = (await client.get("/api/admin/assistant/sessions")).json()
        everything = (await client.get("/api/admin/assistant/sessions?minutes=0")).json()

        assert recent["sessions"] == []
        assert any(s["player_name"] == "Quiet" for s in everything["sessions"])

    async def test_it_reports_the_rung_and_finding_count(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        message = await _turn(db_session, conversation, level=3)
        await _finding(db_session, player, message)
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        row = (await client.get("/api/admin/assistant/sessions")).json()["sessions"][0]

        assert row["ladder_level"] == 3
        assert row["findings"] == 1
        assert row["blocked"] is False

    async def test_a_player_cannot_list_sessions(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await _as(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/assistant/sessions")).status_code == 403


class TestTranscript:
    async def test_an_admin_reads_the_whole_conversation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        await _turn(db_session, conversation, content="the first reply")
        await _as(db_session, client, sign_in, UserRole.ADMIN)

        body = (await client.get(f"/api/admin/assistant/sessions/{player.id}")).json()

        assert body["exists"] is True
        assert body["turns"][0]["content"] == "the first reply"

    async def test_an_organiser_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Staff covers people who need read-only event visibility. This is not that."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        response = await client.get(f"/api/admin/assistant/sessions/{player.id}")

        assert response.status_code == 403

    async def test_opening_one_is_audited(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """So "who looked at this" has an answer."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await _conversation(db_session, player)
        admin = await _as(db_session, client, sign_in, UserRole.ADMIN)

        await client.get(f"/api/admin/assistant/sessions/{player.id}")

        rows = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.action == "assistant.transcript_read")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].actor_user_id == admin.id
        assert rows[0].target_id == player.id

    async def test_the_withheld_text_and_the_scratchpad_are_both_there(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Spec 010 stores the scratchpad so an odd answer can be explained; this
        is the one surface where it is returned."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        conversation = await _conversation(db_session, player)
        await _turn(
            db_session,
            conversation,
            withheld=True,
            reasoning="the model thinking aloud",
            trace=["warden"],
        )
        await _as(db_session, client, sign_in, UserRole.ADMIN)

        turn = (await client.get(f"/api/admin/assistant/sessions/{player.id}")).json()["turns"][0]

        assert turn["original_content"] == "the withheld text"
        assert turn["reasoning_content"] == "the model thinking aloud"
        assert turn["trace"] == ["warden"]

    async def test_a_purged_conversation_degrades(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await _as(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.get(f"/api/admin/assistant/sessions/{player.id}")

        assert response.status_code == 200
        assert response.json()["exists"] is False
        assert response.json()["turns"] == []

    async def test_an_unknown_user_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await _as(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.get(f"/api/admin/assistant/sessions/{uuid.uuid4()}")

        assert response.status_code == 404


class TestTheScratchpadStaysPut:
    async def test_it_never_reaches_a_player_endpoint(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """The spec 010 guarantee, re-asserted exactly where 034 relaxes it: the
        admin transcript is the only place it is returned."""
        import httpx

        from app.services import ai_client
        from tests.factories import make_ladder as _ladder

        await _ladder(db_session)
        ai_client.use_transport(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "model": "test-model",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "A reply.",
                                    "reasoning_content": "SECRET SCRATCHPAD",
                                }
                            }
                        ],
                    },
                )
            )
        )
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        await client.post("/api/assistant/messages", json={"content": "hello"})
        conversation = await client.get("/api/assistant/conversation")

        assert "SECRET SCRATCHPAD" not in conversation.text


class TestMetricsEndpoint:
    async def test_staff_can_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await _as(db_session, client, sign_in, UserRole.ORGANIZER)

        response = await client.get("/api/admin/assistant/metrics")

        assert response.status_code == 200
        body = response.json()
        assert set(body["windows"]) == {"5m", "15m", "60m"}
        assert len(body["rungs"]) == 6

    async def test_a_player_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await _as(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/assistant/metrics")).status_code == 403
