"""Test object factories.

Deliberately thin: they build valid rows with sensible defaults so a test can say
only what it actually cares about.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    Ability,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.instance import ContainerTemplate
from app.models.play import Solve
from app.models.puzzle import ChallengePuzzle, PuzzleKind
from app.models.team import MembershipRole, Team, TeamMembership, TeamVisibility
from app.models.user import User, UserRole, UserSource, UserStatus


async def make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    display_name: str = "Test Player",
    source: UserSource = UserSource.GUEST,
    status: UserStatus = UserStatus.ACTIVE,
    role: UserRole = UserRole.PLAYER,
    entra_object_id: uuid.UUID | None = None,
    theme: str | None = None,
    high_contrast: bool = False,
) -> User:
    user = User(
        email=email or f"player-{uuid.uuid4().hex[:12]}@example.com",
        display_name=display_name,
        source=source,
        status=status,
        role=role,
        entra_object_id=entra_object_id,
        theme=theme,
        high_contrast=high_contrast,
    )
    session.add(user)
    await session.flush()
    return user


async def make_team(
    session: AsyncSession,
    leader: User,
    *,
    name: str | None = None,
    visibility: TeamVisibility = TeamVisibility.PUBLIC,
    join_password_hash: str | None = None,
    max_members: int = 8,
) -> Team:
    team = Team(
        name=name or f"Party {uuid.uuid4().hex[:8]}",
        visibility=visibility,
        join_password_hash=join_password_hash,
        leader_user_id=leader.id,
        max_members=max_members,
    )
    session.add(team)
    await session.flush()
    await add_member(session, team, leader, role=MembershipRole.LEADER)
    return team


async def add_member(
    session: AsyncSession,
    team: Team,
    user: User,
    *,
    role: MembershipRole = MembershipRole.MEMBER,
) -> TeamMembership:
    membership = TeamMembership(
        team_id=team.id,
        user_id=user.id,
        role=role,
        joined_at=datetime.now(UTC),
    )
    session.add(membership)
    await session.flush()
    return membership


async def make_category(
    session: AsyncSession,
    *,
    name: str | None = None,
    display_order: int = 0,
    ability: Ability = Ability.INT,
) -> Category:
    suffix = uuid.uuid4().hex[:8]
    category = Category(
        name=name or f"Category {suffix}",
        slug=(name or f"category-{suffix}").lower().replace(" ", "-"),
        display_order=display_order,
        ability=ability,
    )
    session.add(category)
    await session.flush()
    return category


async def make_challenge(
    session: AsyncSession,
    *,
    category: Category | None = None,
    title: str | None = None,
    state: ChallengeState = ChallengeState.PUBLISHED,
    difficulty: Difficulty = Difficulty.MEDIUM,
    release_at: datetime | None = None,
    pre_release_state: PreReleaseState = PreReleaseState.HIDDEN,
    initial_points: int = 500,
    minimum_points: int = 100,
    decay_threshold: int = 40,
    scoring: ScoringMode = ScoringMode.DYNAMIC,
    decay_basis: DecayBasis = DecayBasis.PLAYERS,
    max_attempts: int | None = None,
    body: str = "Find the flag.",
    answers: list[tuple[MatchType, str]] | None = None,
    ai_ladder_level: int | None = None,
) -> Challenge:
    suffix = uuid.uuid4().hex[:8]
    category = category or await make_category(session)
    challenge = Challenge(
        title=title or f"Challenge {suffix}",
        slug=f"challenge-{suffix}",
        category_id=category.id,
        body=body,
        state=state,
        difficulty=difficulty,
        release_at=release_at,
        pre_release_state=pre_release_state,
        initial_points=initial_points,
        minimum_points=minimum_points,
        decay_threshold=decay_threshold,
        scoring=scoring,
        decay_basis=decay_basis,
        max_attempts=max_attempts,
        ai_ladder_level=ai_ladder_level,
    )
    session.add(challenge)
    await session.flush()

    # `None` means "give it the usual flag"; an explicit `[]` means a challenge
    # with no answer at all, which spec 041's no-flag filter needs to find.
    if answers is None:
        answers = [(MatchType.EXACT, "flag{correct}")]
    for order, (match_type, value) in enumerate(answers):
        session.add(
            ChallengeAnswer(
                challenge_id=challenge.id,
                match_type=match_type,
                value=value,
                options={},
                display_order=order,
            )
        )
    await session.flush()
    return challenge


async def record_solve(
    session: AsyncSession,
    user: User,
    challenge: Challenge,
    *,
    team: Team | None = None,
    xp: int | None = None,
    submitted_at: datetime | None = None,
) -> Solve:
    """A solve, banking XP (spec 015). Defaults the banked XP to the challenge's
    initial points so a plain solve is worth what the challenge is worth."""
    solve = Solve(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_solve=team.id if team else None,
        submitted_at=submitted_at or datetime.now(UTC),
        xp_awarded=xp if xp is not None else challenge.initial_points,
    )
    session.add(solve)
    await session.flush()
    return solve


async def make_template(
    session: AsyncSession,
    *,
    name: str = "Demo Target",
    image: str = "ghcr.io/anders-sec/ctf-demo",
    injects_answer: bool = True,
    shared_instance: bool = False,
    ttl_seconds: int = 3600,
) -> ContainerTemplate:
    template = ContainerTemplate(
        name=name,
        image=image,
        image_tag="v1",
        container_port=8080,
        injects_answer=injects_answer,
        shared_instance=shared_instance,
        ttl_seconds=ttl_seconds,
    )
    session.add(template)
    await session.flush()
    return template


async def make_container_challenge(
    session: AsyncSession,
    template: ContainerTemplate,
    **kwargs,
) -> Challenge:
    """A published challenge wired to a container template."""
    challenge = await make_challenge(session, **kwargs)
    challenge.container_template_id = template.id
    await session.flush()
    return challenge


#: The six ladder flags used throughout the tests. Invented values — the real
#: ones are live answers and never appear in this repository.
LADDER_FLAGS = {
    0: "flag{ladder_zero_test_a1}",
    1: "flag{ladder_one_test_b2}",
    2: "flag{ladder_two_test_c3}",
    3: "flag{ladder_three_test_d4}",
    4: "flag{ladder_four_test_e5}",
    5: "flag{ladder_five_test_f6}",
}


async def make_ladder(
    session: AsyncSession, *, levels: int = 6, category: Category | None = None
) -> list[Challenge]:
    """The System AI ladder: one challenge per rung, each carrying its own flag.

    Needed by anything that drives `assistant_chat.send`, because the engine
    resolves the player's level to a flag through `ai_ladder_level` and degrades
    in character when it cannot.
    """
    # The category name is irrelevant — `ai_ladder_level` is what identifies a
    # rung — and a fixed one collides between tests.
    category = category or await make_category(session)
    built = []
    for level in range(levels):
        built.append(
            await make_challenge(
                session,
                category=category,
                title=f"Ladder {level}",
                ai_ladder_level=level,
                scoring=ScoringMode.STATIC,
                answers=[(MatchType.CASE_INSENSITIVE, LADDER_FLAGS[level])],
            )
        )
    return built


async def make_puzzle(
    session: AsyncSession,
    challenge: Challenge,
    *,
    kind: PuzzleKind = PuzzleKind.WORDLE,
    config: dict | None = None,
) -> ChallengePuzzle:
    """Attach a puzzle to a challenge (spec 044).

    The config goes through the engine's validator, exactly as the admin route
    does — a test fixture that skipped it could set up a puzzle the platform
    would never accept, and then prove something about a state that cannot occur.
    """
    from app.services.puzzles import engine_for

    puzzle = ChallengePuzzle(
        challenge_id=challenge.id,
        kind=kind,
        config=engine_for(kind).validate(config or DEFAULT_PUZZLE_CONFIG[kind]),
    )
    session.add(puzzle)
    await session.flush()
    return puzzle


#: Valid minimal content per kind, so a test that does not care about the puzzle
#: itself does not have to invent one.
DEFAULT_PUZZLE_CONFIG: dict[PuzzleKind, dict] = {
    PuzzleKind.WORDLE: {"answer": "PROXY"},
    PuzzleKind.CONNECTIONS: {
        "groups": [
            {"name": "Ports", "level": 1, "members": ["22", "80", "443", "3389"]},
            {"name": "Hashes", "level": 2, "members": ["MD5", "SHA1", "BCRYPT", "ARGON2"]},
            {"name": "Tools", "level": 3, "members": ["NMAP", "BURP", "HYDRA", "JOHN"]},
            {"name": "Attacks", "level": 4, "members": ["XSS", "CSRF", "SQLI", "SSRF"]},
        ]
    },
    PuzzleKind.CROSSWORD: {
        "width": 3,
        "height": 3,
        "entries": [
            {"direction": "across", "row": 0, "col": 0, "answer": "CAT", "clue": "Feline"},
            {"direction": "across", "row": 1, "col": 0, "answer": "ARE", "clue": "Exist"},
            {"direction": "across", "row": 2, "col": 0, "answer": "TEN", "clue": "Count"},
            {"direction": "down", "row": 0, "col": 0, "answer": "CAT", "clue": "Feline down"},
            {"direction": "down", "row": 0, "col": 1, "answer": "ARE", "clue": "Exist down"},
            {"direction": "down", "row": 0, "col": 2, "answer": "TEN", "clue": "Count down"},
        ],
    },
}
