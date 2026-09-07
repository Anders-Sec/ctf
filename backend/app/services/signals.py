"""Activity that *might* be answer-sharing, surfaced for a human to look at.

Nothing here changes a score, disables an account or messages anyone, and this
module deliberately ships no mechanism that could. `Plan.md` asks for review,
not enforcement.

**These are conversation starters, not evidence.** The people in these findings
are colleagues, and the most common cause of every signal below is two of them
sitting together talking about a puzzle — which is the point of the event. Every
finding therefore carries its innocent explanation alongside the suspicious one,
and the language stays "signal", never "violation".

Everything is computed on demand from what specs 002-004 already record. This
module adds no tracking of its own.
"""

import hashlib
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import Challenge
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.guardrail import AssistantFinding, GuardrailLayer
from app.models.play import Solve, Submission
from app.models.signal import SignalDismissal
from app.models.team import Team, TeamMembership
from app.models.user import User, UserRole, UserStatus

SHARED_ANSWER = "shared_wrong_answer"
CLOSE_SOLVE = "close_behind_solve"
FIRST_TRY = "first_try_solver"
LATE_RECRUIT = "late_recruitment"
CADENCE = "steady_cadence"
SHARED_IP = "shared_ip"
ASSISTANT_EXTRACTION = "assistant_extraction"

#: Strings that mean nothing — everybody types these.
_OBVIOUS = {"test", "flag", "password", "admin", "asdf", "guess", "unknown", "none"}

#: Below this many attempts a cadence is not a pattern.
_CADENCE_MIN_SUBMISSIONS = 12
#: Standard deviation of inter-arrival gaps, in seconds, below which the timing
#: stops looking like a person.
_CADENCE_STDEV_SECONDS = 1.5


@dataclass(frozen=True)
class Finding:
    signal_type: str
    #: Stable across recomputes, so a dismissal sticks to this finding and to
    #: nothing else.
    subject_key: str
    #: Display names of the people involved.
    participants: list[dict[str, str]]
    challenge_title: str | None
    #: What was actually observed. Shown to the reviewer in full.
    evidence: dict[str, Any]
    #: The boring reason this probably happened. Shown beside the evidence.
    innocent_explanation: str
    dismissed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Context:
    settings: Settings
    players: dict[UUID, User] = field(default_factory=dict)
    team_names: dict[UUID, str] = field(default_factory=dict)


def _key(signal_type: str, *parts: object) -> str:
    """A digest of the participants and challenge, order-independent."""
    joined = "|".join(sorted(str(part) for part in parts))
    return hashlib.sha256(f"{signal_type}:{joined}".encode()).hexdigest()[:32]


def _person(context: _Context, user_id: UUID) -> dict[str, str]:
    user = context.players.get(user_id)
    return {
        "user_id": str(user_id),
        "display_name": user.display_name if user else "Unknown",
    }


async def _load_context(db: AsyncSession, settings: Settings) -> _Context:
    players = {
        user.id: user
        for user in (
            await db.execute(
                # Staff are not competing, so they are in no finding.
                select(User).where(User.role == UserRole.PLAYER, User.status != UserStatus.DISABLED)
            )
        )
        .scalars()
        .all()
    }
    team_names = dict((await db.execute(select(Team.id, Team.name))).all())
    return _Context(settings=settings, players=players, team_names=team_names)


async def shared_wrong_answers(db: AsyncSession, context: _Context) -> list[Finding]:
    """The same unusual wrong string from players in different parties.

    Sharing an answer usually means sharing the typo too, which makes this the
    strongest signal available — and it is nearly free, since submitted_value
    is indexed.
    """
    settings = context.settings
    rows = (
        await db.execute(
            select(
                Submission.submitted_value,
                Submission.challenge_id,
                Submission.user_id,
                Submission.team_id_at_submit,
            ).where(
                Submission.is_correct.is_(False),
                func.length(Submission.submitted_value) >= settings.signal_shared_answer_min_length,
            )
        )
    ).all()

    grouped: dict[tuple[str, UUID], dict[UUID, UUID | None]] = defaultdict(dict)
    for value, challenge_id, user_id, team_id in rows:
        if user_id not in context.players:
            continue
        if value.strip().lower() in _OBVIOUS:
            continue
        grouped[(value, challenge_id)][user_id] = team_id

    titles = await _challenge_titles(db)
    findings = []

    for (value, challenge_id), participants in grouped.items():
        # A value used by many players is a popular guess, not a conspiracy.
        if not (2 <= len(participants) <= settings.signal_shared_answer_max_players):
            continue
        # Same-party collaboration is what a party is for.
        teams = {team for team in participants.values() if team is not None}
        partyless = sum(1 for team in participants.values() if team is None)
        if len(teams) + partyless < 2:
            continue

        findings.append(
            Finding(
                signal_type=SHARED_ANSWER,
                subject_key=_key(SHARED_ANSWER, challenge_id, *participants),
                participants=[_person(context, user_id) for user_id in participants],
                challenge_title=titles.get(challenge_id),
                evidence={
                    "value": value,
                    "player_count": len(participants),
                    "parties": [
                        context.team_names.get(team, "—") if team else "no party"
                        for team in participants.values()
                    ],
                },
                innocent_explanation=(
                    "An obvious guess for this challenge, or they were sitting "
                    "together and one read theirs out."
                ),
            )
        )
    return findings


async def close_behind_solves(db: AsyncSession, context: _Context) -> list[Finding]:
    """A first-try solve landing just behind another party's solve."""
    settings = context.settings
    window = timedelta(seconds=settings.signal_close_solve_seconds)

    solves = (
        await db.execute(
            select(
                Solve.challenge_id, Solve.user_id, Solve.team_id_at_solve, Solve.submitted_at
            ).order_by(Solve.challenge_id, Solve.submitted_at)
        )
    ).all()
    wrong_before = await _wrong_attempt_counts(db)
    titles = await _challenge_titles(db)

    by_challenge: dict[UUID, list] = defaultdict(list)
    for challenge_id, user_id, team_id, at in solves:
        if user_id in context.players:
            by_challenge[challenge_id].append((at, user_id, team_id))

    findings = []
    for challenge_id, entries in by_challenge.items():
        for index, (at, user_id, team_id) in enumerate(entries):
            if index == 0:
                continue
            # A first-try solve is the interesting case; someone who worked at
            # it and got there is just a solver.
            if wrong_before.get((user_id, challenge_id), 0) > 0:
                continue

            earlier = [e for e in entries[:index] if at - e[0] <= window]
            others = [e for e in earlier if e[2] is None or e[2] != team_id]
            if not others:
                continue

            previous_at, previous_user, _ = others[-1]
            findings.append(
                Finding(
                    signal_type=CLOSE_SOLVE,
                    subject_key=_key(CLOSE_SOLVE, challenge_id, user_id, previous_user),
                    participants=[
                        _person(context, previous_user),
                        _person(context, user_id),
                    ],
                    challenge_title=titles.get(challenge_id),
                    evidence={
                        "seconds_apart": int((at - previous_at).total_seconds()),
                        "no_wrong_attempts": True,
                        # A general stampede is visible as a stampede.
                        "solves_in_window": len(earlier) + 1,
                    },
                    innocent_explanation=(
                        "An easy challenge, or a wave had just unlocked and "
                        "several people reached it at once."
                    ),
                )
            )
    return findings


async def first_try_solvers(db: AsyncSession, context: _Context) -> list[Finding]:
    """Players who are correct on the first attempt almost every time."""
    settings = context.settings
    solves = (await db.execute(select(Solve.user_id, Solve.challenge_id))).all()
    wrong_before = await _wrong_attempt_counts(db)

    totals: dict[UUID, list[int]] = defaultdict(lambda: [0, 0])
    for user_id, challenge_id in solves:
        if user_id not in context.players:
            continue
        totals[user_id][0] += 1
        if wrong_before.get((user_id, challenge_id), 0) == 0:
            totals[user_id][1] += 1

    findings = []
    for user_id, (total, first_try) in totals.items():
        if total < settings.signal_first_try_min_solves:
            continue
        ratio = first_try / total
        if ratio < settings.signal_first_try_ratio:
            continue

        findings.append(
            Finding(
                signal_type=FIRST_TRY,
                subject_key=_key(FIRST_TRY, user_id),
                participants=[_person(context, user_id)],
                challenge_title=None,
                evidence={
                    "solves": total,
                    "first_try_solves": first_try,
                    "ratio": round(ratio, 2),
                },
                innocent_explanation=(
                    "They are simply good, or they work the problem out fully "
                    "before submitting anything — which is normal play."
                ),
            )
        )
    return findings


async def late_recruitment(db: AsyncSession, context: _Context) -> list[Finding]:
    """Someone joining a party near the end, bringing a pile of solves.

    Not against the rules — it follows from portable scores and open rosters,
    which were deliberate choices. Worth seeing all the same.
    """
    settings = context.settings
    event = await db.get(EventConfig, EVENT_CONFIG_ID)
    if event is None or event.ends_at is None:
        return []

    cutoff = event.ends_at - timedelta(hours=settings.signal_late_recruit_hours)
    joins = (
        await db.execute(
            select(TeamMembership.user_id, TeamMembership.team_id, TeamMembership.joined_at).where(
                TeamMembership.joined_at >= cutoff,
                TeamMembership.removed_at.is_(None),
            )
        )
    ).all()
    if not joins:
        return []

    solve_counts = dict(
        (await db.execute(select(Solve.user_id, func.count()).group_by(Solve.user_id))).all()
    )

    findings = []
    for user_id, team_id, joined_at in joins:
        if user_id not in context.players:
            continue
        brought = solve_counts.get(user_id, 0)
        if brought < settings.signal_late_recruit_min_solves:
            continue

        findings.append(
            Finding(
                signal_type=LATE_RECRUIT,
                subject_key=_key(LATE_RECRUIT, user_id, team_id),
                participants=[_person(context, user_id)],
                challenge_title=None,
                evidence={
                    "party": context.team_names.get(team_id, "—"),
                    "joined_at": joined_at.isoformat(),
                    "solves_brought": brought,
                },
                innocent_explanation=("They were without a party and someone took them in."),
            )
        )
    return findings


async def steady_cadence(db: AsyncSession, context: _Context) -> list[Finding]:
    """Attempts arriving at near-constant intervals.

    Rate limiting already caps how fast someone can submit; this notices the
    *regularity*, which is what separates a script from a person.
    """
    rows = (
        await db.execute(
            select(Submission.user_id, Submission.created_at).order_by(
                Submission.user_id, Submission.created_at
            )
        )
    ).all()

    by_user: dict[UUID, list[datetime]] = defaultdict(list)
    for user_id, at in rows:
        if user_id in context.players:
            by_user[user_id].append(at)

    findings = []
    for user_id, times in by_user.items():
        if len(times) < _CADENCE_MIN_SUBMISSIONS:
            continue
        gaps = [
            (later - earlier).total_seconds()
            for earlier, later in zip(times, times[1:], strict=False)
        ]
        spread = statistics.pstdev(gaps)
        if spread > _CADENCE_STDEV_SECONDS:
            continue

        findings.append(
            Finding(
                signal_type=CADENCE,
                subject_key=_key(CADENCE, user_id),
                participants=[_person(context, user_id)],
                challenge_title=None,
                evidence={
                    "submissions": len(times),
                    "mean_gap_seconds": round(statistics.mean(gaps), 2),
                    "gap_stdev_seconds": round(spread, 2),
                },
                innocent_explanation=("Someone working a wordlist by hand at a steady pace."),
            )
        )
    return findings


async def shared_addresses(db: AsyncSession, context: _Context) -> list[Finding]:
    """Two accounts submitting from one address.

    **Close to useless here** and off by default. Everyone at a work event sits
    behind the same corporate NAT, so this matches most of the field; an
    organiser who does not know that will read it as damning.
    """
    if not context.settings.signal_shared_ip_enabled:
        return []

    rows = (
        await db.execute(
            select(Submission.ip, Submission.user_id).where(Submission.ip.is_not(None)).distinct()
        )
    ).all()

    by_ip: dict[str, set[UUID]] = defaultdict(set)
    for ip, user_id in rows:
        if user_id in context.players:
            by_ip[ip].add(user_id)

    return [
        Finding(
            signal_type=SHARED_IP,
            subject_key=_key(SHARED_IP, ip),
            participants=[_person(context, user_id) for user_id in users],
            challenge_title=None,
            evidence={"address": ip, "player_count": len(users)},
            innocent_explanation=(
                "Almost certainly nothing. A shared corporate network puts the "
                "whole field behind one address."
            ),
        )
        for ip, users in by_ip.items()
        if len(users) >= 2
    ]


async def assistant_extraction(db: AsyncSession, context: _Context) -> list[Finding]:
    """A player who keeps trying to talk the dungeon master out of an answer.

    Computed from `assistant_finding` the same way the other six are computed
    from submissions — no new tracking, and it inherits the dismissal, the
    innocent explanation and the review page. Staff findings are excluded at the
    source (`from_staff`), so our own testing of the filters does not appear.
    """
    settings = context.settings
    rows = (
        await db.execute(
            select(AssistantFinding.user_id, func.count(AssistantFinding.id))
            .where(
                AssistantFinding.layer == GuardrailLayer.INTEGRITY,
                AssistantFinding.from_staff.is_(False),
            )
            .group_by(AssistantFinding.user_id)
        )
    ).all()

    findings = []
    for user_id, count in rows:
        if user_id not in context.players:
            continue
        if count < settings.signal_assistant_extraction_min:
            continue
        findings.append(
            Finding(
                signal_type=ASSISTANT_EXTRACTION,
                subject_key=_key(ASSISTANT_EXTRACTION, user_id),
                participants=[_person(context, user_id)],
                challenge_title=None,
                evidence={"integrity_flags": count},
                innocent_explanation=(
                    "Often harmless. Asking the dungeon master for the flag is a "
                    "joke nearly everyone makes, and every repeat counts here."
                ),
            )
        )
    return findings


_COMPUTERS = {
    SHARED_ANSWER: shared_wrong_answers,
    CLOSE_SOLVE: close_behind_solves,
    FIRST_TRY: first_try_solvers,
    LATE_RECRUIT: late_recruitment,
    CADENCE: steady_cadence,
    SHARED_IP: shared_addresses,
    ASSISTANT_EXTRACTION: assistant_extraction,
}


async def compute(
    db: AsyncSession, settings: Settings, only: str | None = None
) -> dict[str, list[Finding]]:
    """Every signal, or one of them, with dismissals already applied."""
    context = await _load_context(db, settings)
    dismissed = {
        (row.signal_type, row.subject_key)
        for row in (await db.execute(select(SignalDismissal))).scalars().all()
    }

    results: dict[str, list[Finding]] = {}
    for name, computer in _COMPUTERS.items():
        if only is not None and name != only:
            continue
        findings = await computer(db, context)
        results[name] = [f for f in findings if (f.signal_type, f.subject_key) not in dismissed]
    return results


async def _challenge_titles(db: AsyncSession) -> dict[UUID, str]:
    return dict((await db.execute(select(Challenge.id, Challenge.title))).all())


async def _wrong_attempt_counts(db: AsyncSession) -> dict[tuple[UUID, UUID], int]:
    """Wrong attempts per player per challenge, for spotting first-try solves."""
    rows = (
        await db.execute(
            select(Submission.user_id, Submission.challenge_id, func.count())
            .where(Submission.is_correct.is_(False))
            .group_by(Submission.user_id, Submission.challenge_id)
        )
    ).all()
    return {(user_id, challenge_id): count for user_id, challenge_id, count in rows}


async def player_timeline(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """One player's activity in order.

    The screen an organiser actually needs when a signal looks real. Most
    resolve in seconds once this is visible, usually innocently.
    """
    events: list[dict[str, Any]] = []
    titles = await _challenge_titles(db)

    submissions = (
        (
            await db.execute(
                select(Submission)
                .where(Submission.user_id == user_id)
                .order_by(Submission.created_at)
            )
        )
        .scalars()
        .all()
    )
    for row in submissions:
        events.append(
            {
                "at": row.created_at.isoformat(),
                "kind": "solve" if row.is_correct else "attempt",
                "challenge": titles.get(row.challenge_id),
                "detail": row.submitted_value,
                "ip": row.ip,
            }
        )

    from app.models.hint import Hint, HintUnlock

    unlocks = (
        await db.execute(
            select(HintUnlock, Hint)
            .join(Hint, Hint.id == HintUnlock.hint_id)
            .where(HintUnlock.user_id == user_id)
        )
    ).all()
    for unlock, hint in unlocks:
        events.append(
            {
                "at": unlock.unlocked_at.isoformat(),
                "kind": "hint",
                "challenge": titles.get(hint.challenge_id),
                "detail": f"{hint.title} ({unlock.cost_charged} points)",
                "ip": None,
            }
        )

    memberships = (
        await db.execute(
            select(TeamMembership, Team)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(TeamMembership.user_id == user_id)
        )
    ).all()
    for membership, team in memberships:
        events.append(
            {
                "at": membership.joined_at.isoformat(),
                "kind": "party_join",
                "challenge": None,
                "detail": f"Joined {team.name}",
                "ip": None,
            }
        )
        if membership.removed_at is not None:
            why = f" ({membership.removal_reason.value})" if membership.removal_reason else ""
            events.append(
                {
                    "at": membership.removed_at.isoformat(),
                    "kind": "party_leave",
                    "challenge": None,
                    "detail": f"Left {team.name}{why}",
                    "ip": None,
                }
            )

    events.sort(key=lambda event: event["at"])
    return events


def now() -> datetime:
    return datetime.now(UTC)
