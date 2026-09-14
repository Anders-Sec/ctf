"""Generate a coherent sample event, for working on the platform with data in it.

Everything it creates is tagged with :data:`SAMPLE_PREFIX` in its slug (or, for
rows with no slug, drawn from a fixed name list), so ``purge`` can take exactly
what it made back out and leave anything real alone.

Deliberately **not** available in production: it invents players, solves and
scores, and an accidental click during the real event would be a mess to unpick.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError
from app.models.challenge import (
    Ability,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    Difficulty,
    MatchType,
    RequirementType,
    UnlockRequirement,
    default_scoring_for,
    minimum_points_for,
    points_for,
)
from app.models.hint import Hint
from app.models.play import Solve
from app.models.skill import ChallengeSkill, Skill
from app.models.team import MembershipRole, Team, TeamMembership, TeamVisibility
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services import unlocks as unlock_service

#: Marks everything this module creates, so a purge is precise.
SAMPLE_PREFIX = "sample-"
SAMPLE_EMAIL_DOMAIN = "sample.invalid"

#: Difficulty now derives the value, so the plan says how hard, not how many
#: points (spec 018). Skills are real seeded ones, so the sample exercises the
#: per-challenge skill system rather than inventing its own.
CHALLENGE_PLAN = [
    ("Warm-Up", "First Steps", Difficulty.VERY_EASY),
    ("Warm-Up", "Second Steps", Difficulty.VERY_EASY),
    ("Warm-Up", "Third Steps", Difficulty.EASY),
    ("Web", "Cookie Jar", Difficulty.EASY),
    ("Web", "Injection Point", Difficulty.MEDIUM),
    ("Web", "Broken Auth", Difficulty.HARD),
    ("Forensics", "Packet Trace", Difficulty.MEDIUM),
    ("Forensics", "Deleted Evidence", Difficulty.HARD),
    ("Crypto", "Caesar's Ghost", Difficulty.EASY),
    ("Crypto", "Weak Keys", Difficulty.NEARLY_IMPOSSIBLE),
]


class SampleDataUnavailable(AppError):
    status_code = 403
    code = "sample_data_unavailable"
    message = "Sample data cannot be generated in production."


@dataclass
class SampleSummary:
    categories: int = 0
    challenges: int = 0
    skills: int = 0
    hints: int = 0
    players: int = 0
    teams: int = 0
    solves: int = 0
    gates: int = 0
    achievements: int = 0


def _slug(*parts: str) -> str:
    return SAMPLE_PREFIX + "-".join(p.lower().replace(" ", "-") for p in parts)


async def generate(db: AsyncSession) -> SampleSummary:
    """Build a small but complete event: four zones of challenges with
    prerequisites and gates, hints, players, a party, and solves.

    Classes are **not** created here — the real 48-class roster is seeded by
    migration (spec 024), and sample players draw from it like anyone else.

    Idempotent by way of ``purge``: generating twice replaces rather than
    duplicates, so the button is safe to press repeatedly.
    """
    await purge(db)
    summary = SampleSummary()
    now = datetime.now(UTC)

    # Four wings: an open starter area, then progressively gated ones — the
    # shape the dungeon map is meant to show off.
    zones = [
        ("Warm-Up", Ability.INT, 1),
        ("Web", Ability.STR, 2),
        ("Forensics", Ability.DEX, 3),
        ("Crypto", Ability.INT, 4),
    ]
    categories: dict[str, Category] = {}
    for name, ability, order in zones:
        category = Category(
            name=f"{name} (sample)",
            slug=_slug(name),
            display_order=order,
            description=f"Sample {name} challenges.",
            ability=ability,
        )
        db.add(category)
        categories[name] = category
        summary.categories += 1
    await db.flush()

    challenges = await _build_challenges(db, categories, now, summary)
    await _build_gates(db, categories, challenges, summary)
    await _build_players(db, challenges, summary)

    return summary


async def _build_challenges(
    db: AsyncSession,
    categories: dict[str, Category],
    now: datetime,
    summary: SampleSummary,
) -> dict[str, Challenge]:
    built: dict[str, Challenge] = {}
    xp_base = get_settings().xp_base
    for zone, title, difficulty in CHALLENGE_PLAN:
        flag = f"flag{{{title.lower().replace(' ', '_')}}}"
        challenge = Challenge(
            title=f"{title} (sample)",
            slug=_slug(title),
            category_id=categories[zone].id,
            body=f"Sample challenge: {title}. The flag is `{flag}`.",
            difficulty=difficulty,
            state=ChallengeState.PUBLISHED,
            # Seeded from the difficulty ladder. Real challenges set their own XP
            # (spec 040); sample data has nobody to type one, and the ladder is
            # still what a plausible spread looks like.
            initial_points=points_for(difficulty, xp_base),
            minimum_points=minimum_points_for(difficulty, xp_base),
            scoring=default_scoring_for(difficulty),
        )
        db.add(challenge)
        built[title] = challenge
        summary.challenges += 1
    await db.flush()

    for title, challenge in built.items():
        db.add(
            ChallengeAnswer(
                challenge_id=challenge.id,
                match_type=MatchType.CASE_INSENSITIVE,
                value=f"flag{{{title.lower().replace(' ', '_')}}}",
                options={},
                display_order=0,
            )
        )

    # Attach real (seeded) skills, so the skills table has something in it and
    # the overlap rule is visible: one solve feeds several skills at full value.
    wanted = {
        "Injection Point": ["Injection Artistry", "Reflexive Inspect Element"],
        "Cookie Jar": ["Auth Bypass", "Chronic URL Bar Tinkering"],
        "Weak Keys": ["Cryptanalysis", "Whiteboard Math Anxiety"],
        "Packet Trace": ["Evidence Handling", "Compulsive Ctrl+F"],
    }
    names = {n for group in wanted.values() for n in group}
    seeded = {
        name: skill_id
        for skill_id, name in (
            await db.execute(select(Skill.id, Skill.name).where(Skill.name.in_(names)))
        ).all()
    }
    for title, skill_names in wanted.items():
        for skill_name in skill_names:
            skill_id = seeded.get(skill_name)
            if skill_id is not None:
                db.add(ChallengeSkill(challenge_id=built[title].id, skill_id=skill_id))
                summary.skills += 1

    # A couple of hints, so the deferred-hint economy has something to show.
    for title, cost in (("Injection Point", 50), ("Weak Keys", 100)):
        db.add(
            Hint(
                challenge_id=built[title].id,
                title="Where to look",
                body=f"Sample hint for {title}.",
                cost=cost,
                display_order=0,
            )
        )
        summary.hints += 1

    # One scheduled release, to exercise the pre-release path.
    built["Broken Auth"].release_at = now + timedelta(hours=6)
    await db.flush()
    return built


async def _build_gates(
    db: AsyncSession,
    categories: dict[str, Category],
    challenges: dict[str, Challenge],
    summary: SampleSummary,
) -> None:
    """A guided path: a chain in the starter zone, then wings that open on
    progress — one per gate type, so every kind is visible on the map."""
    chain = [
        ("Second Steps", "First Steps"),
        ("Third Steps", "Second Steps"),
        ("Injection Point", "Cookie Jar"),
        ("Broken Auth", "Injection Point"),
        ("Deleted Evidence", "Packet Trace"),
    ]
    for gated, required in chain:
        await unlock_service.add_requirement(
            db,
            challenge_id=challenges[gated].id,
            requirement_type=RequirementType.CHALLENGE_SOLVED,
            required_challenge_id=challenges[required].id,
        )
        summary.gates += 1

    zone_gates = [
        # Clear most of the starter wing to open Web.
        (
            "Web",
            {
                "requirement_type": RequirementType.SOLVES_IN_CATEGORY,
                "required_category_id": categories["Warm-Up"].id,
                "threshold": 2,
            },
        ),
        ("Forensics", {"requirement_type": RequirementType.MIN_XP, "threshold": 400}),
        (
            "Crypto",
            {
                "requirement_type": RequirementType.SOLVES_IN_CATEGORY,
                "required_category_id": categories["Web"].id,
                "threshold": 1,
            },
        ),
    ]
    for zone, spec in zone_gates:
        await unlock_service.add_requirement(db, category_id=categories[zone].id, **spec)
        summary.gates += 1


async def _build_players(
    db: AsyncSession, challenges: dict[str, Challenge], summary: SampleSummary
) -> None:
    """A handful of players at different depths, so the board, XP curve, levels
    and party rules all have something to show."""
    names = [
        ("Thorin Flagsplitter", ["First Steps", "Second Steps", "Third Steps", "Cookie Jar"]),
        ("Mira Nullbyte", ["First Steps", "Second Steps", "Packet Trace"]),
        ("Garrick Overflow", ["First Steps", "Cookie Jar"]),
        ("Sable Ciphersong", ["First Steps", "Second Steps"]),
        ("Pip Rootward", ["First Steps"]),
    ]

    players: list[User] = []
    for display_name, _ in names:
        user = User(
            email=f"{SAMPLE_PREFIX}{display_name.split()[0].lower()}@{SAMPLE_EMAIL_DOMAIN}",
            display_name=display_name,
            source=UserSource.GUEST,
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
            approved_at=datetime.now(UTC),
        )
        db.add(user)
        players.append(user)
        summary.players += 1
    await db.flush()

    party = Team(
        name="The Sample Delvers",
        visibility=TeamVisibility.PUBLIC,
        leader_user_id=players[0].id,
        max_members=8,
    )
    db.add(party)
    summary.teams += 1
    await db.flush()

    joined = datetime.now(UTC)
    for index, user in enumerate(players[:3]):
        db.add(
            TeamMembership(
                team_id=party.id,
                user_id=user.id,
                role=MembershipRole.LEADER if index == 0 else MembershipRole.MEMBER,
                joined_at=joined,
            )
        )

    solved_at = datetime.now(UTC) - timedelta(hours=2)
    for user, (_, titles) in zip(players, names, strict=True):
        member_of = party.id if user in players[:3] else None
        for offset, title in enumerate(titles):
            challenge = challenges[title]
            db.add(
                Solve(
                    user_id=user.id,
                    challenge_id=challenge.id,
                    team_id_at_solve=member_of,
                    submitted_at=solved_at + timedelta(minutes=offset * 7),
                    # Banked at face value; the point is to populate the curve.
                    xp_awarded=challenge.initial_points,
                )
            )
            summary.solves += 1
    await db.flush()


async def purge(db: AsyncSession) -> None:
    """Remove everything ``generate`` made, and nothing else.

    Ordered so foreign keys never block: solves and memberships first, then the
    rows they pointed at.
    """
    challenge_ids = (
        (await db.execute(select(Challenge.id).where(Challenge.slug.startswith(SAMPLE_PREFIX))))
        .scalars()
        .all()
    )
    user_ids = (
        (await db.execute(select(User.id).where(User.email.endswith(f"@{SAMPLE_EMAIL_DOMAIN}"))))
        .scalars()
        .all()
    )
    category_ids = (
        (await db.execute(select(Category.id).where(Category.slug.startswith(SAMPLE_PREFIX))))
        .scalars()
        .all()
    )

    if challenge_ids:
        await db.execute(sql_delete(Solve).where(Solve.challenge_id.in_(challenge_ids)))
    if user_ids:
        await db.execute(sql_delete(Solve).where(Solve.user_id.in_(user_ids)))
        await db.execute(sql_delete(TeamMembership).where(TeamMembership.user_id.in_(user_ids)))
        await db.execute(sql_delete(Team).where(Team.leader_user_id.in_(user_ids)))
        await db.execute(sql_delete(User).where(User.id.in_(user_ids)))

    if challenge_ids:
        # Requirements cascade from either side, but drop them explicitly so a
        # gate pointing at a sample challenge from a real one cannot linger.
        await db.execute(
            sql_delete(UnlockRequirement).where(UnlockRequirement.challenge_id.in_(challenge_ids))
        )
        await db.execute(sql_delete(Challenge).where(Challenge.id.in_(challenge_ids)))

    if category_ids:
        await db.execute(
            sql_delete(UnlockRequirement).where(UnlockRequirement.category_id.in_(category_ids))
        )
        await db.execute(sql_delete(Category).where(Category.id.in_(category_ids)))

    # Deliberately does not touch character_class. The sample data used to own
    # three classes named Rogue, Seer and Wizard, from before the real roster
    # existed; 024 seeded a real Rogue and Wizard, so this delete would have
    # taken two roster entries with it and returned their players to Classless.
    await db.flush()


def ensure_allowed(is_production: bool) -> None:
    if is_production:
        raise SampleDataUnavailable


# --- Dungeon mode (spec 025) -------------------------------------------------


class DungeonNotSeeded(AppError):
    status_code = 409
    code = "dungeon_not_seeded"
    message = "The real categories and skills are not seeded yet."


#: Three or four per zone. Demo scale deliberately: the goal is seeing every
#: area in use, not load — a load-shaped dataset is the 012 harness's job.
_TITLES = ("Foothold", "Deeper In", "The Locked Door", "What Waits Below")

#: Rises with the zone's depth in the progression graph, so the early wings are
#: approachable and the deep ones are not.
_DIFFICULTY_BY_DEPTH = {
    0: (Difficulty.VERY_EASY, Difficulty.VERY_EASY, Difficulty.EASY),
    1: (Difficulty.VERY_EASY, Difficulty.EASY, Difficulty.EASY, Difficulty.MEDIUM),
    2: (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.HARD),
    3: (Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.HARD, Difficulty.HARD),
}
_DEEP = (Difficulty.MEDIUM, Difficulty.HARD, Difficulty.HARD, Difficulty.VERY_HARD)


async def generate_dungeon(db: AsyncSession) -> SampleSummary:
    """Fill the **real** dungeon: sample challenges in the real 22 zones, with
    the real skills attached (spec 025).

    Creates no categories, no skills and no classes — it reads them. That is the
    whole point: the existing generator builds a world of its own, which cannot
    show you whether the actual progression graph, gates and class roster work.
    """
    await purge(db)
    summary = SampleSummary()
    now = datetime.now(UTC)

    categories = list(
        (
            await db.execute(
                select(Category)
                .where(~Category.slug.startswith(SAMPLE_PREFIX))
                .order_by(Category.display_order)
            )
        )
        .scalars()
        .all()
    )
    if not categories:
        raise DungeonNotSeeded()

    depths = await _zone_depths(db, categories)
    skills_by_category = await _skills_by_category(db)
    all_skill_ids = [sid for group in skills_by_category.values() for sid in group]

    xp_base = get_settings().xp_base
    built: list[Challenge] = []
    for category in categories:
        depth = depths.get(category.id, 0)
        ladder = _DIFFICULTY_BY_DEPTH.get(depth, _DEEP)
        for index, difficulty in enumerate(ladder):
            title = f"{category.name}: {_TITLES[index % len(_TITLES)]}"
            challenge = Challenge(
                title=f"{title} (sample)",
                slug=_slug(category.slug, str(index)),
                category_id=category.id,
                body=f"Sample challenge in {category.name}.",
                difficulty=difficulty,
                state=ChallengeState.PUBLISHED,
                initial_points=points_for(difficulty, xp_base),
                minimum_points=minimum_points_for(difficulty, xp_base),
                scoring=default_scoring_for(difficulty),
            )
            db.add(challenge)
            built.append(challenge)
            summary.challenges += 1
    await db.flush()

    for index, challenge in enumerate(built):
        db.add(
            ChallengeAnswer(
                challenge_id=challenge.id,
                match_type=MatchType.CASE_INSENSITIVE,
                value=f"flag{{{challenge.slug}}}",
                options={},
                display_order=0,
            )
        )
        # This zone's own skills, plus one from elsewhere every few challenges so
        # the overlap rule is visible: one solve feeds every attached skill in
        # full, which is what lets a skill level move at all.
        attach = list(skills_by_category.get(challenge.category_id, []))[:3]
        if all_skill_ids and index % 3 == 0:
            attach.append(all_skill_ids[index % len(all_skill_ids)])
        for skill_id in dict.fromkeys(attach):
            db.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill_id))
            summary.skills += 1

        if index % 7 == 0:
            db.add(
                Hint(
                    challenge_id=challenge.id,
                    title="Where to look",
                    body=f"Sample hint for {challenge.title}.",
                    cost=50,
                    display_order=0,
                )
            )
            summary.hints += 1
    await db.flush()

    await _build_dungeon_players(db, categories, depths, built, now, summary)

    # Achievements never backfill (spec 028), so seeding them against solves
    # that already exist awards nothing. Running the evaluator here is what
    # keeps the feature visible in the environment it is built in.
    await _award_achievements(db, summary)
    return summary


async def _award_achievements(db: AsyncSession, summary: SampleSummary) -> None:
    from app.services import achievements as achievement_service

    users = (
        (await db.execute(select(User.id).where(User.email.endswith(f"@{SAMPLE_EMAIL_DOMAIN}"))))
        .scalars()
        .all()
    )
    for user_id in users:
        earned = await achievement_service.evaluate(db, user_id, achievement_service.SOLVE)
        summary.achievements += len(earned)


async def _zone_depths(db: AsyncSession, categories: list[Category]) -> dict:
    """How far each zone sits from a starting zone, along the real gate graph.

    Depth drives the difficulty ladder, so the sample content matches the shape
    the progression graph already describes rather than inventing its own.
    """
    rows = (
        await db.execute(
            select(UnlockRequirement.required_category_id, UnlockRequirement.category_id).where(
                UnlockRequirement.category_id.is_not(None),
                UnlockRequirement.required_category_id.is_not(None),
            )
        )
    ).all()
    forward: dict = {}
    gated = set()
    for source, target in rows:
        forward.setdefault(source, []).append(target)
        gated.add(target)

    depths = {c.id: 0 for c in categories if c.id not in gated}
    frontier = list(depths)
    while frontier:
        node = frontier.pop(0)
        for nxt in forward.get(node, []):
            if nxt not in depths:
                depths[nxt] = depths[node] + 1
                frontier.append(nxt)
    # A zone nothing reaches still needs a depth; treat it as deep.
    for category in categories:
        depths.setdefault(category.id, 3)
    return depths


async def _skills_by_category(db: AsyncSession) -> dict:
    rows = (await db.execute(select(Skill.id, Skill.category_id))).all()
    grouped: dict = {}
    for skill_id, category_id in rows:
        if category_id is not None:
            grouped.setdefault(category_id, []).append(skill_id)
    return grouped


async def _build_dungeon_players(
    db: AsyncSession,
    categories: list[Category],
    depths: dict,
    challenges: list[Challenge],
    now: datetime,
    summary: SampleSummary,
) -> None:
    """Players at a spread of depths, so the map, the gates and the class roster
    all have something to show.

    Progress is expressed as "how deep this player has pushed": a player only
    ever holds solves in zones at or above their reach, so nobody carries a solve
    in a wing they could not have opened.
    """
    by_category: dict = {}
    for challenge in challenges:
        by_category.setdefault(challenge.category_id, []).append(challenge)

    # (name, how deep they have pushed, how much of each reachable zone they cleared)
    roster = [
        ("Thorin Flagsplitter", 3, 1.0),
        ("Mira Nullbyte", 2, 0.8),
        ("Garrick Overflow", 2, 0.5),
        ("Sable Ciphersong", 1, 0.7),
        ("Pip Rootward", 1, 0.4),
        ("Bex Hexdump", 0, 1.0),
        ("Quill Ashgrove", 0, 0.5),
    ]

    players: list[User] = []
    for display_name, _, _ in roster:
        user = User(
            email=f"{SAMPLE_PREFIX}{display_name.split()[0].lower()}@{SAMPLE_EMAIL_DOMAIN}",
            display_name=display_name,
            source=UserSource.GUEST,
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
            approved_at=now,
        )
        db.add(user)
        players.append(user)
        summary.players += 1
    await db.flush()

    party = Team(
        name="The Sample Delvers",
        visibility=TeamVisibility.PUBLIC,
        leader_user_id=players[0].id,
        max_members=8,
    )
    db.add(party)
    summary.teams += 1
    await db.flush()

    for index, user in enumerate(players[:3]):
        db.add(
            TeamMembership(
                team_id=party.id,
                user_id=user.id,
                role=MembershipRole.LEADER if index == 0 else MembershipRole.MEMBER,
                joined_at=now,
            )
        )

    solved_at = now - timedelta(hours=6)
    for user, (_, reach, share) in zip(players, roster, strict=True):
        member_of = party.id if user in players[:3] else None
        offset = 0
        for category in categories:
            if depths.get(category.id, 0) > reach:
                continue
            in_zone = by_category.get(category.id, [])
            for challenge in in_zone[: max(1, round(len(in_zone) * share))]:
                db.add(
                    Solve(
                        user_id=user.id,
                        challenge_id=challenge.id,
                        team_id_at_solve=member_of,
                        submitted_at=solved_at + timedelta(minutes=offset * 5),
                        xp_awarded=challenge.initial_points,
                    )
                )
                summary.solves += 1
                offset += 1
    await db.flush()
