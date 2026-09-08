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
from app.models.character_class import CharacterClass
from app.models.hint import Hint
from app.models.play import Solve
from app.models.skill import ChallengeSkill, Skill
from app.models.team import MembershipRole, Team, TeamMembership, TeamVisibility
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services import unlocks as unlock_service

#: Marks everything this module creates, so a purge is precise.
SAMPLE_PREFIX = "sample-"
SAMPLE_EMAIL_DOMAIN = "sample.invalid"

#: Classes are still sample-only — the real list is being written (spec 018).
CLASSES = ["Rogue", "Seer", "Wizard"]

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
    classes: int = 0
    hints: int = 0
    players: int = 0
    teams: int = 0
    solves: int = 0
    gates: int = 0


def _slug(*parts: str) -> str:
    return SAMPLE_PREFIX + "-".join(p.lower().replace(" ", "-") for p in parts)


async def generate(db: AsyncSession) -> SampleSummary:
    """Build a small but complete event: skills, classes, four zones of
    challenges with prerequisites and gates, hints, players, a party, and solves.

    Idempotent by way of ``purge``: generating twice replaces rather than
    duplicates, so the button is safe to press repeatedly.
    """
    await purge(db)
    summary = SampleSummary()
    now = datetime.now(UTC)

    for order, name in enumerate(CLASSES):
        db.add(
            CharacterClass(
                name=name,
                display_order=order,
                description=f"A sample {name.lower()}.",
            )
        )
        summary.classes += 1
    await db.flush()

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
            # Derived from difficulty, exactly as the admin editor does.
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

    await db.execute(sql_delete(CharacterClass).where(CharacterClass.name.in_(CLASSES)))
    await db.flush()


def ensure_allowed(is_production: bool) -> None:
    if is_production:
        raise SampleDataUnavailable
