"""Getting the event's results out (spec 056).

Content export was already solved — spec 040 for challenges, 027 for the map —
so an event can be *rebuilt*. Nothing exported what *happened*, and after five
days the only way to get the standings out was a screenshot.

Two moments need this and they are not the same. The awards, on the last
afternoon, under time pressure, with people waiting: standings, category
winners, first bloods, read off something printable. And the write-up the week
after: everything, in a form a spreadsheet will open. One file serves neither.
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.challenge import Category, Challenge
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.services import admin_scoreboard

#: Excel is where these are opened, and without a BOM every non-ASCII display
#: name arrives mangled.
BOM = "﻿"

#: Streamed in batches rather than materialised: the largest table is
#: submissions, on the order of 10^5 rows for this event.
BATCH = 1000


def _row(values: Iterable[Any]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(
        ["" if value is None else value for value in values]
    )
    return buffer.getvalue()


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


async def _stream(header: list[str], rows: AsyncIterator[list[Any]]) -> AsyncIterator[str]:
    yield BOM + _row(header)
    async for row in rows:
        yield _row(row)


async def standings(db: AsyncSession, redis: Redis) -> AsyncIterator[str]:
    """The admin board's numbers, unchanged.

    Same computation the page shows, so an export can never disagree with the
    screen somebody read the winner off.
    """
    board = await admin_scoreboard.board(db, redis)

    async def rows() -> AsyncIterator[list[Any]]:
        for entry in board["players"]:
            yield [
                "player",
                entry["rank"],
                entry["display_name"],
                entry.get("team_name") or "",
                entry["solve_count"],
                entry["solve_points"],
                entry["adjustment_points"],
                entry["score"],
                entry.get("last_gain_at") or "",
            ]
        for entry in board["teams"]:
            yield [
                "party",
                entry["rank"],
                entry["name"],
                entry["member_count"],
                entry["solve_count"],
                entry["solve_points"],
                entry["adjustment_points"],
                entry["score"],
                entry.get("last_gain_at") or "",
            ]

    return _stream(
        [
            "board",
            "rank",
            "name",
            "secondary",
            "solves",
            "solve_points",
            "adjustment_points",
            "total",
            "last_gain_at",
        ],
        rows(),
    )


async def awards(db: AsyncSession, redis: Redis) -> AsyncIterator[str]:
    """The sheet that saves the closing afternoon.

    Grouped by award with a header per group rather than one wide table: this is
    read aloud, so it is a document more than a dataset, and it is the one
    export where that is the right call.
    """
    board = await admin_scoreboard.board(db, redis)
    players = board["players"]

    zones = dict((await db.execute(select(Category.id, Category.name))).all())
    challenge_rows = (
        await db.execute(select(Challenge.id, Challenge.title, Challenge.category_id))
    ).all()
    titles = {row[0]: row[1] for row in challenge_rows}
    zone_of = {row[0]: row[2] for row in challenge_rows}

    solves = (
        await db.execute(
            select(
                Solve.user_id, Solve.challenge_id, Solve.submitted_at, Solve.xp_awarded
            ).order_by(Solve.submitted_at)
        )
    ).all()
    names = dict((await db.execute(select(User.id, User.display_name))).all())

    async def rows() -> AsyncIterator[list[Any]]:
        yield ["OVERALL", "", "", ""]
        yield ["rank", "player", "total", "decided at"]
        for entry in players[:10]:
            yield [
                entry["rank"],
                entry["display_name"],
                entry["score"],
                entry.get("last_gain_at") or "",
            ]

        yield ["", "", "", ""]
        yield ["TOP PER ZONE", "", "", ""]
        yield ["zone", "player", "xp in zone", ""]
        per_zone: dict[Any, dict[Any, int]] = {}
        for user_id, challenge_id, _at, xp in solves:
            zone = zone_of.get(challenge_id)
            if zone is None:
                continue
            per_zone.setdefault(zone, {})
            per_zone[zone][user_id] = per_zone[zone].get(user_id, 0) + int(xp or 0)
        for zone_id, zone_name in sorted(zones.items(), key=lambda pair: pair[1]):
            tally = per_zone.get(zone_id)
            if not tally:
                # A zone nobody completed still gets a line, so nothing is
                # silently missing from a sheet being read out.
                yield [zone_name, "— nobody —", 0, ""]
                continue
            winner, xp = max(tally.items(), key=lambda pair: pair[1])
            yield [zone_name, names.get(winner, "unknown"), xp, ""]

        yield ["", "", "", ""]
        yield ["FIRST BLOOD", "", "", ""]
        yield ["challenge", "player", "at", "lead over second"]
        first: dict[Any, list[tuple[Any, datetime]]] = {}
        for user_id, challenge_id, at, _xp in solves:
            first.setdefault(challenge_id, []).append((user_id, at))
        for challenge_id, hits in sorted(first.items(), key=lambda pair: titles.get(pair[0], "")):
            winner, at = hits[0]
            lead = ""
            if len(hits) > 1:
                delta = hits[1][1] - at
                lead = f"{int(delta.total_seconds() // 60)} min"
            yield [
                titles.get(challenge_id, "unknown"),
                names.get(winner, "unknown"),
                _iso(at),
                lead,
            ]

        yield ["", "", "", ""]
        yield ["COMPLETIONISTS", "", "", ""]
        yield ["player", "zone", "", ""]
        zone_sizes: dict[Any, int] = {}
        for _cid, _title, category_id in challenge_rows:
            if category_id is not None:
                zone_sizes[category_id] = zone_sizes.get(category_id, 0) + 1
        cleared: dict[Any, dict[Any, int]] = {}
        for user_id, challenge_id, _at, _xp in solves:
            zone = zone_of.get(challenge_id)
            if zone is None:
                continue
            cleared.setdefault(user_id, {})
            cleared[user_id][zone] = cleared[user_id].get(zone, 0) + 1
        for user_id, per in cleared.items():
            for zone_id, count in per.items():
                if zone_sizes.get(zone_id) and count >= zone_sizes[zone_id]:
                    yield [names.get(user_id, "unknown"), zones.get(zone_id, "unknown"), "", ""]

    return _stream(["award", "b", "c", "d"], rows())


async def solves_csv(db: AsyncSession) -> AsyncIterator[str]:
    async def rows() -> AsyncIterator[list[Any]]:
        stmt = (
            select(
                Solve.submitted_at,
                User.display_name,
                Team.name,
                Challenge.title,
                Category.name,
                Solve.xp_awarded,
            )
            .join(User, User.id == Solve.user_id)
            .outerjoin(Team, Team.id == Solve.team_id_at_solve)
            .outerjoin(Challenge, Challenge.id == Solve.challenge_id)
            .outerjoin(Category, Category.id == Challenge.category_id)
            .order_by(Solve.submitted_at)
            .execution_options(yield_per=BATCH)
        )
        result = await db.stream(stmt)
        async for at, player, party, challenge, zone, xp in result:
            yield [_iso(at), player, party or "", challenge or "", zone or "", xp]

    return _stream(["submitted_at", "player", "party_at_solve", "challenge", "zone", "xp"], rows())


async def submissions_csv(db: AsyncSession, *, full: bool) -> AsyncIterator[str]:
    """Every attempt.

    The redacted form is the default and is not a lesser export: `submitted_value`
    is, in aggregate, *a list of every flag in the event*, because every correct
    submission is one. What analysis actually wants — "was this challenge's flag
    format confusing?" — is answered by the derived columns without carrying the
    answers.
    """
    answers_by_challenge: dict[Any, set[str]] = {}
    if not full:
        from app.models.challenge import ChallengeAnswer

        for challenge_id, value in (
            await db.execute(select(ChallengeAnswer.challenge_id, ChallengeAnswer.value))
        ).all():
            if value:
                answers_by_challenge.setdefault(challenge_id, set()).add(_fold(value))

    header = ["submitted_at", "player", "challenge", "is_correct", "value_length"]
    header += ["value", "ip"] if full else ["near_miss"]

    async def rows() -> AsyncIterator[list[Any]]:
        stmt = (
            select(
                Submission.created_at,
                User.display_name,
                Challenge.title,
                Submission.is_correct,
                Submission.submitted_value,
                Submission.ip,
                Submission.challenge_id,
            )
            .join(User, User.id == Submission.user_id)
            .outerjoin(Challenge, Challenge.id == Submission.challenge_id)
            .order_by(Submission.created_at)
            .execution_options(yield_per=BATCH)
        )
        result = await db.stream(stmt)
        async for at, player, challenge, correct, value, ip, challenge_id in result:
            base = [_iso(at), player, challenge or "", correct, len(value or "")]
            if full:
                yield [*base, value, ip or ""]
            else:
                yield [*base, _near_miss(value, answers_by_challenge.get(challenge_id, set()))]

    return _stream(header, rows())


def _fold(value: str) -> str:
    """Case and whitespace only.

    Deliberately not ``answers.normalise``, which needs a ChallengeAnswer and
    applies per-rule semantics. This is a similarity measure for a report, not
    an answer check, and it must not accidentally accept anything.
    """
    return " ".join(value.split()).casefold()


def _near_miss(value: str | None, answers: set[str]) -> str:
    """Whether a wrong answer was nearly right, without saying what it was."""
    if not value or not answers:
        return ""
    candidate = _fold(value)
    if candidate in answers:
        return "exact"
    for answer in answers:
        if abs(len(candidate) - len(answer)) > 2:
            continue
        if _within_two(candidate, answer):
            return "near"
    return ""


def _within_two(a: str, b: str) -> bool:
    """Levenshtein distance of at most two, decided without building a matrix."""
    if a == b:
        return True
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > 2:
            return False
        previous = current
    return previous[-1] <= 2


async def players_csv(db: AsyncSession) -> AsyncIterator[str]:
    async def rows() -> AsyncIterator[list[Any]]:
        solve_totals = dict(
            (
                await db.execute(
                    select(Solve.user_id, func.coalesce(func.sum(Solve.xp_awarded), 0)).group_by(
                        Solve.user_id
                    )
                )
            ).all()
        )
        parties = dict(
            (
                await db.execute(
                    select(TeamMembership.user_id, Team.name)
                    .join(Team, Team.id == TeamMembership.team_id)
                    .where(TeamMembership.removed_at.is_(None))
                )
            ).all()
        )
        users = (await db.execute(select(User).order_by(User.display_name))).scalars().all()
        for user in users:
            yield [
                user.display_name,
                user.email,
                user.source.value,
                user.role.value,
                user.status.value,
                parties.get(user.id, ""),
                int(solve_totals.get(user.id, 0)),
                _iso(user.created_at),
                _iso(user.last_login_at),
            ]

    return _stream(
        ["name", "email", "source", "role", "status", "party", "xp", "joined", "last_seen"],
        rows(),
    )


async def parties_csv(db: AsyncSession) -> AsyncIterator[str]:
    async def rows() -> AsyncIterator[list[Any]]:
        counts = dict(
            (
                await db.execute(
                    select(TeamMembership.team_id, func.count())
                    .where(TeamMembership.removed_at.is_(None))
                    .group_by(TeamMembership.team_id)
                )
            ).all()
        )
        leaders = dict((await db.execute(select(User.id, User.display_name))).all())
        # Disbanded parties included: they are part of what happened.
        teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
        for team in teams:
            yield [
                team.name,
                team.visibility.value,
                int(counts.get(team.id, 0)),
                team.max_members,
                leaders.get(team.leader_user_id, ""),
                _iso(team.created_at),
                _iso(team.disbanded_at),
            ]

    return _stream(
        ["name", "visibility", "members", "max_members", "leader", "created", "disbanded"],
        rows(),
    )


async def adjustments_csv(db: AsyncSession) -> AsyncIterator[str]:
    async def rows() -> AsyncIterator[list[Any]]:
        actor = User.__table__.alias("actor")
        subject = User.__table__.alias("subject")
        stmt = (
            select(
                ScoreAdjustment.created_at,
                subject.c.display_name,
                Team.name,
                ScoreAdjustment.points,
                ScoreAdjustment.reason,
                actor.c.display_name,
                ScoreAdjustment.reverses_id,
            )
            .outerjoin(subject, subject.c.id == ScoreAdjustment.user_id)
            .outerjoin(Team, Team.id == ScoreAdjustment.team_id)
            .outerjoin(actor, actor.c.id == ScoreAdjustment.created_by_user_id)
            .order_by(ScoreAdjustment.created_at)
        )
        for at, player, party, points, reason, by, reverses in (await db.execute(stmt)).all():
            yield [
                _iso(at),
                player or party or "",
                "party" if party else "player",
                points,
                reason,
                by or "system",
                "yes" if reverses else "",
            ]

    return _stream(
        ["created_at", "subject", "kind", "points", "reason", "by", "is_reversal"], rows()
    )


async def audit_csv(db: AsyncSession) -> AsyncIterator[str]:
    async def rows() -> AsyncIterator[list[Any]]:
        stmt = (
            select(
                AuditLog.created_at,
                User.display_name,
                AuditLog.action,
                AuditLog.target_type,
                AuditLog.target_id,
                AuditLog.reason,
            )
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .order_by(AuditLog.created_at)
            .execution_options(yield_per=BATCH)
        )
        result = await db.stream(stmt)
        async for at, actor, action, target_type, target_id, reason in result:
            yield [_iso(at), actor or "system", action, target_type, target_id or "", reason or ""]

    return _stream(["created_at", "actor", "action", "target_type", "target_id", "reason"], rows())


#: Everything the archive holds, and how to build each one. The full submissions
#: form is deliberately absent — it is downloaded on its own, deliberately.
ARCHIVE: dict[str, str] = {
    "standings.csv": "standings",
    "awards.csv": "awards",
    "solves.csv": "solves",
    "submissions.csv": "submissions",
    "players.csv": "players",
    "parties.csv": "parties",
    "adjustments.csv": "adjustments",
    "audit-log.csv": "audit",
}


async def build(
    name: str, db: AsyncSession, redis: Redis, *, full: bool = False
) -> AsyncIterator[str]:
    if name == "standings":
        return await standings(db, redis)
    if name == "awards":
        return await awards(db, redis)
    if name == "solves":
        return await solves_csv(db)
    if name == "submissions":
        return await submissions_csv(db, full=full)
    if name == "players":
        return await players_csv(db)
    if name == "parties":
        return await parties_csv(db)
    if name == "adjustments":
        return await adjustments_csv(db)
    if name == "audit":
        return await audit_csv(db)
    raise KeyError(name)


async def archive(db: AsyncSession, redis: Redis, event_name: str) -> bytes:
    """Every export plus a manifest, in one zip.

    Held in memory rather than streamed into the response: a zip's central
    directory is written last, and the whole archive for this event is a few
    megabytes.
    """
    buffer = io.BytesIO()
    counts: dict[str, int] = {}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for filename, key in ARCHIVE.items():
            chunks: list[str] = []
            async for chunk in await build(key, db, redis):
                chunks.append(chunk)
            # Minus the header row.
            counts[filename] = max(len(chunks) - 1, 0)
            bundle.writestr(filename, "".join(chunks))

        import json

        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "event": event_name,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "files": counts,
                    "note": (
                        "submissions.csv is the redacted form. The full form, which "
                        "contains every flag submitted, is exported separately and "
                        "deliberately."
                    ),
                },
                indent=2,
            ),
        )

    return buffer.getvalue()
