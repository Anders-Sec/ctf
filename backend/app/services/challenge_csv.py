"""Challenge import and export as CSV (spec 026).

Authoring 240-odd challenges through a web form is the wrong tool. This is the
spreadsheet round-trip: a template with every row pre-filled with its category
and difficulty, and an import that reads the same shape back.

The template's difficulty spread is not decorative. Eleven rows per category as
2/2/3/2/1/1 across the ladder totals **1,900 XP per category**, and across 22
categories **41,800** — the ~2,000 and ~42,000 that spec 018 budgeted. Filling
the template in as-is therefore produces an event whose economy already matches
the curve levels and abilities were tuned against.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError
from app.models.challenge import (
    MINIMUM_POINTS_FRACTION,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    Difficulty,
    MatchType,
    default_scoring_for,
    minimum_points_for,
    points_for,
)
from app.models.skill import ChallengeSkill, Skill

#: The column order of both the template and the export, so a round-trip is
#: byte-comparable and a diff between two exports is readable.
COLUMNS = [
    "category",
    "title",
    "difficulty",
    "description",
    "flag",
    "points",
    "state",
    "max_attempts",
    "release_at",
    "skills",
    #: Which rung of the System AI ladder (spec 033). Blank for almost every
    #: challenge. Without it the ladder cannot be authored from the spreadsheet
    #: at all, and six challenges would have to be hand-edited after every
    #: import.
    "ai_ladder_level",
]

#: 2/2/3/2/1/1 = 11 rows, 1,900 XP. See the module docstring.
DEFAULT_LADDER = (
    [Difficulty.VERY_EASY] * 2
    + [Difficulty.EASY] * 2
    + [Difficulty.MEDIUM] * 3
    + [Difficulty.HARD] * 2
    + [Difficulty.VERY_HARD]
    + [Difficulty.NEARLY_IMPOSSIBLE]
)

#: Intro gates the whole dungeon, so it gets no very-hard or nearly-impossible
#: row: a wall at the front door stops everyone, not just the people who want it.
INTRO_LADDER = [Difficulty.VERY_EASY] * 4 + [Difficulty.EASY] * 4 + [Difficulty.MEDIUM] * 3

INTRO_SLUG = "intro"


class ImportRejected(AppError):
    status_code = 422
    code = "csv_rejected"
    message = "The file could not be imported."


@dataclass
class RowError:
    row: int
    column: str
    problem: str


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = False
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def ladder_for(category: Category) -> list[Difficulty]:
    return list(INTRO_LADDER if category.slug == INTRO_SLUG else DEFAULT_LADDER)


async def build_template(db: AsyncSession) -> str:
    """A row for every challenge an admin is expected to write.

    Category and difficulty are filled in; everything else is theirs. Difficulty
    is a suggestion in a spreadsheet cell, not a rule — it is there so that
    doing nothing produces a balanced event.
    """
    categories = list(
        (await db.execute(select(Category).order_by(Category.display_order))).scalars().all()
    )
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for category in categories:
        for difficulty in ladder_for(category):
            writer.writerow(
                {c: "" for c in COLUMNS}
                | {"category": category.name, "difficulty": difficulty.value}
            )
    return out.getvalue()


async def build_export(db: AsyncSession) -> str:
    """Current challenges in the template's shape, so export → edit → import
    round-trips. Also the backup that makes import safe to experiment with."""
    rows = (
        await db.execute(
            select(Challenge, Category)
            .join(Category, Category.id == Challenge.category_id)
            .order_by(Category.display_order, Challenge.title)
        )
    ).all()

    answers: dict[UUID, str] = {
        challenge_id: value
        for challenge_id, value in (
            await db.execute(
                select(ChallengeAnswer.challenge_id, ChallengeAnswer.value).order_by(
                    ChallengeAnswer.display_order
                )
            )
        ).all()
    }
    skills = await _skill_names_by_challenge(db)
    xp_base = get_settings().xp_base

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for challenge, category in rows:
        writer.writerow(
            {
                "category": category.name,
                "title": challenge.title,
                "difficulty": challenge.difficulty.value,
                "description": challenge.body or "",
                "flag": answers.get(challenge.id, ""),
                # Only written when it differs from what difficulty would derive,
                # so an ordinary export stays a file of difficulties.
                "points": (
                    challenge.initial_points
                    if challenge.initial_points != points_for(challenge.difficulty, xp_base)
                    else ""
                ),
                "state": challenge.state.value,
                "max_attempts": challenge.max_attempts or "",
                "release_at": (challenge.release_at.isoformat() if challenge.release_at else ""),
                "skills": "; ".join(skills.get(challenge.id, [])),
                "ai_ladder_level": (
                    "" if challenge.ai_ladder_level is None else challenge.ai_ladder_level
                ),
            }
        )
    return out.getvalue()


async def import_csv(db: AsyncSession, text: str, *, dry_run: bool = False) -> ImportReport:
    """Parse, validate the whole file, then apply it — in that order.

    Nothing is written unless every row is good. A file with an error in row 200
    that had already written 199 challenges would leave an admin unable to tell
    what landed without reading all of them; refusing the file outright is the
    kinder failure.
    """
    report = ImportReport(dry_run=dry_run)

    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except csv.Error as exc:
        raise ImportRejected(f"That file is not readable as CSV: {exc}") from exc

    if reader.fieldnames is None:
        raise ImportRejected("The file has no header row.")
    missing = {"category", "title", "difficulty"} - set(reader.fieldnames)
    if missing:
        raise ImportRejected(f"The header is missing: {', '.join(sorted(missing))}.")

    categories = await _categories_by_key(db)
    skills = await _skills_by_name(db)
    existing = await _existing_by_key(db)

    planned: list[tuple[int, dict, Category, Difficulty, list[UUID]]] = []
    seen: set[tuple[UUID, str]] = set()
    #: Rung -> the line that claimed it. Two rows claiming the same rung would
    #: hit the partial unique index halfway through the apply; catching it here
    #: keeps the "nothing is written unless every row is good" promise.
    seen_rungs: dict[int, int] = {}

    for index, raw in enumerate(rows):
        # +2: one for the header, one because spreadsheets count from 1.
        line = index + 2
        row = {k: (v or "").strip() for k, v in raw.items() if k}

        if not row.get("title"):
            # An untouched template row, not a mistake.
            report.skipped += 1
            continue

        category = categories.get(row.get("category", "").lower())
        if category is None:
            report.errors.append(
                RowError(line, "category", f"No category named {row.get('category')!r}.")
            )
            continue

        try:
            difficulty = Difficulty(row.get("difficulty", "").lower())
        except ValueError:
            report.errors.append(
                RowError(
                    line,
                    "difficulty",
                    f"{row.get('difficulty')!r} is not one of: "
                    + ", ".join(d.value for d in Difficulty),
                )
            )
            continue

        key = (category.id, row["title"].lower())
        if key in seen:
            report.errors.append(
                RowError(line, "title", "Another row already uses this title in this category.")
            )
            continue
        seen.add(key)

        skill_ids: list[UUID] = []
        bad_skill = None
        for name in (s.strip() for s in row.get("skills", "").split(";") if s.strip()):
            skill_id = skills.get(name.lower())
            if skill_id is None:
                bad_skill = name
                break
            skill_ids.append(skill_id)
        if bad_skill is not None:
            # Refused rather than skipped: a typo must not silently produce a
            # challenge that feeds no skill at all.
            report.errors.append(RowError(line, "skills", f"No skill named {bad_skill!r}."))
            continue

        state_error = _validate_state(row)
        if state_error:
            report.errors.append(RowError(line, *state_error))
            continue

        release_error = _validate_release_at(row)
        if release_error:
            report.errors.append(RowError(line, *release_error))
            continue

        attempts_error = _validate_max_attempts(row)
        if attempts_error:
            report.errors.append(RowError(line, *attempts_error))
            continue

        points_error = _validate_points(row)
        if points_error:
            report.errors.append(RowError(line, *points_error))
            continue

        ladder_error = _validate_ladder_level(row, line, seen_rungs)
        if ladder_error:
            report.errors.append(RowError(line, *ladder_error))
            continue
        if row.get("ai_ladder_level"):
            seen_rungs[int(row["ai_ladder_level"])] = line

        planned.append((line, row, category, difficulty, skill_ids))

    if report.errors:
        return report

    for _, row, category, _difficulty, _skill_ids in planned:
        if (category.id, row["title"].lower()) in existing:
            report.updated += 1
        else:
            report.created += 1

    if dry_run:
        return report

    for _, row, category, difficulty, skill_ids in planned:
        await _apply(db, row, category, difficulty, skill_ids, existing)
    await db.flush()
    return report


def _validate_state(row: dict) -> tuple[str, str] | None:
    value = row.get("state", "")
    if not value:
        return None
    try:
        ChallengeState(value.lower())
    except ValueError:
        return ("state", f"{value!r} is not one of: " + ", ".join(s.value for s in ChallengeState))
    return None


def _validate_release_at(row: dict) -> tuple[str, str] | None:
    value = row.get("release_at", "")
    if not value:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return ("release_at", f"{value!r} is not an ISO timestamp.")
    return None


def _validate_ladder_level(
    row: dict, line: int, seen_rungs: dict[int, int]
) -> tuple[str, str] | None:
    value = row.get("ai_ladder_level", "")
    if not value:
        return None
    if not value.isdigit() or not (0 <= int(value) <= 5):
        return ("ai_ladder_level", f"{value!r} is not a rung between 0 and 5.")
    claimed = seen_rungs.get(int(value))
    if claimed is not None:
        return ("ai_ladder_level", f"Line {claimed} already claims ladder level {value}.")
    return None


def _validate_points(row: dict) -> tuple[str, str] | None:
    value = row.get("points", "")
    if not value:
        return None
    if not value.isdigit() or int(value) < 1:
        return ("points", f"{value!r} is not a positive whole number.")
    return None


def _validate_max_attempts(row: dict) -> tuple[str, str] | None:
    value = row.get("max_attempts", "")
    if not value:
        return None
    if not value.isdigit() or int(value) < 1:
        return ("max_attempts", f"{value!r} is not a positive whole number.")
    return None


async def _apply(
    db: AsyncSession,
    row: dict,
    category: Category,
    difficulty: Difficulty,
    skill_ids: list[UUID],
    existing: dict[tuple[UUID, str], Challenge],
) -> None:
    xp_base = get_settings().xp_base
    challenge = existing.get((category.id, row["title"].lower()))

    if challenge is None:
        challenge = Challenge(
            title=row["title"],
            slug=await _unique_slug(db, row["title"]),
            category_id=category.id,
        )
        db.add(challenge)

    challenge.title = row["title"]
    challenge.body = row.get("description", "")
    challenge.difficulty = difficulty
    # Difficulty derives the XP, exactly as the admin editor does. `points` is
    # the deliberate override (spec 033): areas differ in size, and six ladder
    # levels have to total what an eleven-challenge zone does. Without the
    # column, a re-import would silently reset them.
    override = int(row["points"]) if row.get("points") else None
    challenge.initial_points = override or points_for(difficulty, xp_base)
    challenge.minimum_points = (
        max(1, int(override * MINIMUM_POINTS_FRACTION))
        if override
        else minimum_points_for(difficulty, xp_base)
    )
    challenge.scoring = default_scoring_for(difficulty)
    challenge.state = (
        ChallengeState(row["state"].lower())
        if row.get("state")
        else (challenge.state if challenge.id else ChallengeState.DRAFT)
    )
    challenge.max_attempts = int(row["max_attempts"]) if row.get("max_attempts") else None
    challenge.ai_ladder_level = (
        int(row["ai_ladder_level"]) if row.get("ai_ladder_level") else None
    )
    challenge.release_at = (
        datetime.fromisoformat(row["release_at"]) if row.get("release_at") else None
    )
    await db.flush()

    if row.get("flag"):
        answer = (
            (
                await db.execute(
                    select(ChallengeAnswer).where(ChallengeAnswer.challenge_id == challenge.id)
                )
            )
            .scalars()
            .first()
        )
        if answer is None:
            db.add(
                ChallengeAnswer(
                    challenge_id=challenge.id,
                    match_type=MatchType.CASE_INSENSITIVE,
                    value=row["flag"],
                    options={},
                    display_order=0,
                )
            )
        else:
            answer.value = row["flag"]

    if skill_ids:
        await db.execute(
            ChallengeSkill.__table__.delete().where(ChallengeSkill.challenge_id == challenge.id)
        )
        for skill_id in skill_ids:
            db.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill_id))


async def _unique_slug(db: AsyncSession, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-") or "challenge"
    slug = base
    suffix = 2
    while await db.scalar(select(Challenge.id).where(Challenge.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


async def _categories_by_key(db: AsyncSession) -> dict[str, Category]:
    """Name *and* slug both resolve, so a hand-edited file is forgiving."""
    categories = list((await db.execute(select(Category))).scalars().all())
    keyed: dict[str, Category] = {}
    for category in categories:
        keyed[category.name.lower()] = category
        keyed[category.slug.lower()] = category
    return keyed


async def _skills_by_name(db: AsyncSession) -> dict[str, UUID]:
    rows = (await db.execute(select(Skill.id, Skill.name))).all()
    return {name.lower(): skill_id for skill_id, name in rows}


async def _existing_by_key(db: AsyncSession) -> dict[tuple[UUID, str], Challenge]:
    challenges = list((await db.execute(select(Challenge))).scalars().all())
    return {(c.category_id, c.title.lower()): c for c in challenges}


async def _skill_names_by_challenge(db: AsyncSession) -> dict[UUID, list[str]]:
    rows = (
        await db.execute(
            select(ChallengeSkill.challenge_id, Skill.name)
            .join(Skill, Skill.id == ChallengeSkill.skill_id)
            .order_by(Skill.name)
        )
    ).all()
    grouped: dict[UUID, list[str]] = {}
    for challenge_id, name in rows:
        grouped.setdefault(challenge_id, []).append(name)
    return grouped
