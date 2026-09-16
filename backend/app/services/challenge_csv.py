"""Challenge import and export as CSV (specs 026, 040).

Authoring 240-odd challenges through a web form is the wrong tool. This is the
spreadsheet round-trip: a template with every row pre-filled with its category
and difficulty, and an import that reads the same shape back.

Spec 026 wrote this for a person filling the file in by hand and kept it narrow —
one flag, no hints, no boss, no prerequisites. Spec 040 widened it, because the
file is now generated rather than typed: **every authored property of a challenge
is a column**, with the list-shaped ones carried as JSON in a single cell. An
import lands a challenge finished, with nothing left to patch up in the editor.

The template's difficulty spread is not decorative. Eleven rows per category as
2/2/3/2/1/1 across the ladder totals **1,900 XP per category**, and across 22
categories **41,800** — the ~2,000 and ~42,000 that spec 018 budgeted. Difficulty
no longer *derives* that XP (spec 040); it fills the template's `xp` column in,
which is the last thing still reading the ladder table. Filling the template in
as-is therefore still produces an event whose economy matches the curve levels
and abilities were tuned against, but the number is now a cell an author owns.
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError
from app.models.challenge import (
    MINIMUM_POINTS_FRACTION,
    BossTier,
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    RequirementType,
    ScoringMode,
    UnlockRequirement,
    points_for,
)
from app.models.hint import Hint, HintUnlock
from app.models.instance import ContainerTemplate
from app.models.skill import ChallengeSkill, Skill
from app.services import answers as answer_service

#: The column order of both the template and the export, so a round-trip is
#: byte-comparable and a diff between two exports is readable.
#:
#: Wide on purpose. The file is written by a session rather than typed by a
#: person, so completeness beats brevity: a column missing here is a property
#: that has to be re-entered by hand in the admin UI after every import.
COLUMNS = [
    # Identity and content
    "category",
    "title",
    #: Optional, and the match key when present — so a title can be *renamed*
    #: without the import creating a second challenge next to the old one.
    "slug",
    "difficulty",
    "description",
    # XP
    "xp",
    "minimum_xp",
    "scoring",
    "decay_threshold",
    "decay_basis",
    # Availability
    "state",
    "release_at",
    "pre_release_state",
    "max_attempts",
    # Relations
    "flag",
    "flags",
    "hints",
    "unlocks",
    "skills",
    "boss_tier",
    "container_template",
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

#: Set by 033's own seed from the ladder's flag, never authored — a requirement
#: list naming it would hand the dungeon's secret route to everyone.
UNAUTHORABLE_REQUIREMENTS = frozenset({RequirementType.AI_LADDER_LEAK})

#: Which extra columns each requirement type reads. A row carrying a field its
#: type would never look at is refused rather than silently ignored, matching
#: what the admin endpoint already does.
REQUIREMENT_FIELDS: dict[RequirementType, set[str]] = {
    RequirementType.CHALLENGE_SOLVED: {"challenge"},
    RequirementType.MIN_XP: {"threshold"},
    RequirementType.SKILL_LEVEL: {"skill", "threshold"},
    RequirementType.SOLVES_IN_CATEGORY: {"category", "threshold"},
    RequirementType.PERCENT_IN_CATEGORY: {"category", "threshold"},
    RequirementType.PLAYER_LEVEL: {"threshold"},
}


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


@dataclass
class _Planned:
    """One validated row, ready to apply.

    ``None`` on a list field means the column was blank — "not mentioned", which
    leaves whatever the challenge already has alone. An empty list means the cell
    said ``[]``, which is the explicit "clear this set". Keeping those two apart
    is the whole reason these are ``| None`` rather than plain lists.
    """

    line: int
    row: dict[str, str]
    category: Category
    difficulty: Difficulty
    skill_ids: list[UUID] | None
    flags: list[dict[str, Any]] | None
    hints: list[dict[str, Any]] | None
    unlocks: list[dict[str, Any]] | None
    boss_tier: BossTier | None
    container_template_id: UUID | None
    existing: Challenge | None


def ladder_for(category: Category) -> list[Difficulty]:
    return list(INTRO_LADDER if category.slug == INTRO_SLUG else DEFAULT_LADDER)


def default_minimum_xp(xp: int) -> int:
    """The floor decay stops at, when the file did not name one."""
    return max(1, int(xp * MINIMUM_POINTS_FRACTION))


async def build_template(db: AsyncSession) -> str:
    """A row for every challenge an admin is expected to write.

    Category, difficulty and a suggested XP are filled in; everything else is
    theirs. The suggestion is there so that doing nothing produces a balanced
    event — it is a number in a cell, not a rule.
    """
    categories = list(
        (await db.execute(select(Category).order_by(Category.display_order))).scalars().all()
    )
    xp_base = get_settings().xp_base
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for category in categories:
        for difficulty in ladder_for(category):
            writer.writerow(
                {c: "" for c in COLUMNS}
                | {
                    "category": category.name,
                    "difficulty": difficulty.value,
                    "xp": points_for(difficulty, xp_base),
                }
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

    answers = await _answers_by_challenge(db)
    hints = await _hints_by_challenge(db)
    unlocks = await _unlocks_by_challenge(db)
    skills = await _skill_names_by_challenge(db)
    templates = {
        template_id: name
        for template_id, name in (
            await db.execute(select(ContainerTemplate.id, ContainerTemplate.name))
        ).all()
    }
    titles = {challenge.id: f"{category.name}/{challenge.title}" for challenge, category in rows}
    names = await _id_names(db)

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for challenge, category in rows:
        rules = answers.get(challenge.id, [])
        writer.writerow(
            {
                "category": category.name,
                "title": challenge.title,
                "slug": challenge.slug,
                "difficulty": challenge.difficulty.value,
                "description": challenge.body or "",
                "xp": challenge.initial_points,
                # Only written when it is not the plain 40%, so an ordinary
                # export does not carry a derivable number on every row.
                "minimum_xp": (
                    ""
                    if challenge.minimum_points == default_minimum_xp(challenge.initial_points)
                    else challenge.minimum_points
                ),
                "scoring": challenge.scoring.value,
                "decay_threshold": challenge.decay_threshold,
                "decay_basis": challenge.decay_basis.value,
                "state": challenge.state.value,
                "release_at": (challenge.release_at.isoformat() if challenge.release_at else ""),
                "pre_release_state": challenge.pre_release_state.value,
                "max_attempts": challenge.max_attempts or "",
                # The simple case stays a word in a cell; anything else becomes
                # JSON. A file of ordinary challenges therefore stays readable.
                "flag": _simple_flag(rules),
                "flags": "" if _simple_flag(rules) or not rules else _dump_flags(rules),
                "hints": _dump_hints(hints.get(challenge.id, [])),
                "unlocks": _dump_unlocks(unlocks.get(challenge.id, []), titles, names),
                "skills": "; ".join(skills.get(challenge.id, [])),
                "boss_tier": challenge.boss_tier.value if challenge.boss_tier else "",
                "container_template": templates.get(challenge.container_template_id, ""),
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
    headers = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = {"category", "title", "difficulty"} - headers
    if missing:
        raise ImportRejected(f"The header is missing: {', '.join(sorted(missing))}.")
    if "points" in headers:
        # Refused rather than ignored: reading it as blank would import every
        # deliberate override as a default, and nobody would notice in 242 rows.
        raise ImportRejected("The `points` column is now `xp`. Rename the column and re-upload.")

    lookups = await _Lookups.load(db)
    planned: list[_Planned] = []
    seen_titles: set[tuple[UUID, str]] = set()
    seen_slugs: dict[str, int] = {}
    #: Rung -> the line that claimed it. Two rows claiming the same rung would
    #: hit the partial unique index halfway through the apply; catching it here
    #: keeps the "nothing is written unless every row is good" promise.
    seen_rungs: dict[int, int] = {}
    for index, raw in enumerate(rows):
        # +2: one for the header, one because spreadsheets count from 1.
        line = index + 2
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}

        if not row.get("title"):
            # An untouched template row, not a mistake.
            report.skipped += 1
            continue

        entry = _plan_row(row, line, lookups, report, seen_titles, seen_slugs, seen_rungs)
        if entry is None:
            continue

        hint_error = _check_hints_are_droppable(entry, lookups)
        if hint_error:
            report.errors.append(RowError(line, *hint_error))
            continue

        planned.append(entry)

    if not report.errors:
        _check_boss_slots(planned, lookups, report)
    if not report.errors:
        _resolve_unlocks(planned, lookups, report)

    if report.errors:
        return report

    for entry in planned:
        if entry.existing is not None:
            report.updated += 1
        else:
            report.created += 1

    if dry_run:
        return report

    for entry in planned:
        await _apply(db, entry)
    await db.flush()

    # Requirements last, in their own pass: a row may require a challenge that
    # another row in this same file has only just created.
    created_ids = {entry.line: entry.existing.id for entry in planned if entry.existing}
    for entry in planned:
        if entry.unlocks is not None and entry.existing is not None:
            await _sync_unlocks(db, entry.existing, entry.unlocks, created_ids)
    await db.flush()
    return report


# --------------------------------------------------------------------------
# Row planning
# --------------------------------------------------------------------------


def _plan_row(
    row: dict[str, str],
    line: int,
    lookups: "_Lookups",
    report: ImportReport,
    seen_titles: set[tuple[UUID, str]],
    seen_slugs: dict[str, int],
    seen_rungs: dict[int, int],
) -> _Planned | None:
    """Validate one row into a :class:`_Planned`, or record why it cannot be.

    Returns ``None`` and appends to ``report.errors`` on the first problem: a row
    with a bad category tells you nothing useful about its flags.
    """

    def fail(column: str, problem: str) -> None:
        report.errors.append(RowError(line, column, problem))

    category = lookups.categories.get(row.get("category", "").lower())
    if category is None:
        # Names the zones that do exist (spec 043). A 242-row file refused over
        # one unknown name should not leave an admin guessing which name was
        # right — and the import deliberately will not invent a zone, because a
        # typo must not produce one no map draws and no ability feeds.
        known = ", ".join(sorted(lookups.zone_names))
        fail(
            "category",
            f"No area named {row.get('category')!r}. Areas are created in the "
            f"platform, not by import. These exist: {known}.",
        )
        return None

    try:
        difficulty = Difficulty(row.get("difficulty", "").lower())
    except ValueError:
        fail(
            "difficulty",
            f"{row.get('difficulty')!r} is not one of: " + ", ".join(d.value for d in Difficulty),
        )
        return None

    slug = row.get("slug", "").lower()
    if slug:
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            fail("slug", f"{row.get('slug')!r} may only hold letters, digits and hyphens.")
            return None
        claimed = seen_slugs.get(slug)
        if claimed is not None:
            fail("slug", f"Line {claimed} already uses this slug.")
            return None
        seen_slugs[slug] = line

    # The slug is the match key when it is there, so a title can be edited
    # without the import creating a second challenge beside the old one.
    existing = (
        lookups.by_slug.get(slug)
        if slug
        else lookups.by_title.get((category.id, row["title"].lower()))
    )

    key = (category.id, row["title"].lower())
    if key in seen_titles:
        fail("title", "Another row already uses this title in this category.")
        return None
    seen_titles.add(key)

    # A title colliding with a *different* challenge in the same category is a
    # duplicate the (category, title) match key could not survive.
    clash = lookups.by_title.get(key)
    if clash is not None and existing is not None and clash.id != existing.id:
        fail("title", "Another challenge in this category already uses this title.")
        return None

    for column, check in (
        ("state", _enum_check(ChallengeState)),
        ("pre_release_state", _enum_check(PreReleaseState)),
        ("scoring", _enum_check(ScoringMode)),
        ("decay_basis", _enum_check(DecayBasis)),
        ("release_at", _timestamp_check),
        ("xp", _positive_check),
        ("minimum_xp", _positive_check),
        ("decay_threshold", _threshold_check),
        ("max_attempts", _positive_check),
    ):
        problem = check(row.get(column, ""))
        if problem:
            fail(column, problem)
            return None

    xp = int(row["xp"]) if row.get("xp") else None
    minimum = int(row["minimum_xp"]) if row.get("minimum_xp") else None
    ceiling = xp if xp is not None else (existing.initial_points if existing else None)
    if minimum is not None and ceiling is not None and minimum > ceiling:
        fail("minimum_xp", f"A floor of {minimum} is above this challenge's {ceiling} XP.")
        return None

    boss_tier: BossTier | None = None
    if row.get("boss_tier"):
        try:
            boss_tier = BossTier(row["boss_tier"].lower())
        except ValueError:
            fail(
                "boss_tier",
                f"{row['boss_tier']!r} is not one of: " + ", ".join(t.value for t in BossTier),
            )
            return None

    container_template_id = None
    if row.get("container_template"):
        matches = lookups.templates.get(row["container_template"].lower(), [])
        if not matches:
            fail(
                "container_template",
                f"No container template named {row['container_template']!r}.",
            )
            return None
        if len(matches) > 1:
            # Template names are not unique, so an ambiguous one has to be
            # resolved in the UI rather than guessed at here.
            fail(
                "container_template",
                f"{len(matches)} templates are named {row['container_template']!r}; "
                "rename them so the file can name one.",
            )
            return None
        container_template_id = matches[0]

    ladder_error = _validate_ladder_level(row, line, seen_rungs)
    if ladder_error:
        fail(*ladder_error)
        return None
    if row.get("ai_ladder_level"):
        seen_rungs[int(row["ai_ladder_level"])] = line

    skill_ids: list[UUID] | None = None
    if row.get("skills"):
        skill_ids = []
        for name in (s.strip() for s in row["skills"].split(";") if s.strip()):
            skill_id = lookups.skills.get(name.lower())
            if skill_id is None:
                # Refused rather than skipped: a typo must not silently produce
                # a challenge that feeds no skill at all.
                fail("skills", f"No skill named {name!r}.")
                return None
            skill_ids.append(skill_id)

    flags, problem = _parse_flags(row)
    if problem:
        fail(*problem)
        return None

    # A per-team flag is minted by a container at launch, so a dynamic rule
    # without one is a challenge nobody can ever solve (spec 046). And a static
    # rule sitting beside it is the shareable answer the dynamic rule exists to
    # remove — both are refused here rather than found mid-event.
    if flags and any(f["match_type"] == MatchType.DYNAMIC for f in flags):
        if container_template_id is None:
            fail(
                "flags",
                "A dynamic flag is minted by a container at launch. "
                "This row needs a container_template.",
            )
            return None
        if any(f["match_type"] != MatchType.DYNAMIC for f in flags):
            fail(
                "flags",
                "A dynamic flag cannot share a row with a static one — the "
                "static value is the same for every team and would be the way "
                "round it.",
            )
            return None

    hints, problem = _parse_hints(row)
    if problem:
        fail(*problem)
        return None

    unlocks, problem = _parse_unlocks(row, lookups)
    if problem:
        fail(*problem)
        return None

    return _Planned(
        line=line,
        row=row,
        category=category,
        difficulty=difficulty,
        skill_ids=skill_ids,
        flags=flags,
        hints=hints,
        unlocks=unlocks,
        boss_tier=boss_tier,
        container_template_id=container_template_id,
        existing=existing,
    )


def _check_boss_slots(planned: list[_Planned], lookups: "_Lookups", report: ImportReport) -> None:
    """One boss per zone (spec 031), checked against the file *and* the platform.

    The database has a partial unique index that would catch a collision too, but
    only halfway through the apply — which would break the promise that a refused
    file changes nothing. Checking here also lets the error name whatever is
    already holding the slot, which the index cannot.
    """
    #: zone -> (owner, name). The owner is a line number when this file makes the
    #: boss, and a challenge id when something it does not touch already is one.
    holders: dict[UUID, tuple[int | UUID, str]] = {
        boss.category_id: (boss.id, boss.title) for boss in lookups.bosses
    }

    # A row overrides whatever the database says about its own challenge, so a
    # file that demotes one boss and promotes another is not a collision.
    for entry in planned:
        if entry.existing is None:
            continue
        held = holders.get(entry.existing.category_id)
        if held is not None and held[0] == entry.existing.id:
            del holders[entry.existing.category_id]

    for entry in planned:
        if entry.boss_tier is None:
            continue
        held = holders.get(entry.category.id)
        if held is not None:
            who = f"Line {held[0]}" if isinstance(held[0], int) else f"{held[1]!r}"
            report.errors.append(
                RowError(
                    entry.line,
                    "boss_tier",
                    f"{who} already holds this zone's boss slot.",
                )
            )
            continue
        holders[entry.category.id] = (entry.line, entry.row["title"])


def _check_hints_are_droppable(entry: _Planned, lookups: "_Lookups") -> tuple[str, str] | None:
    """Refuse to drop a hint somebody paid for.

    Import reconciles hints by position, so a shorter list than the challenge
    already has means deleting the surplus. Deleting one that has unlocks would
    erase the record of a purchase, so the file is refused and the admin deletes
    it deliberately in the UI instead.
    """
    if entry.hints is None or entry.existing is None:
        return None
    current = lookups.hints.get(entry.existing.id, [])
    for hint, unlock_count in current[len(entry.hints) :]:
        if unlock_count:
            return (
                "hints",
                f"Dropping {hint.title!r} would erase {unlock_count} purchase(s). "
                "Delete it in the admin UI if that is what you want.",
            )
    return None


def _resolve_unlocks(planned: list[_Planned], lookups: "_Lookups", report: ImportReport) -> None:
    """Point every ``challenge_solved`` requirement at a real challenge.

    Done after every row is planned rather than inline, so a prerequisite may
    appear *later* in the file than the challenge it gates — which is how a
    generated file, ordered by category, actually comes out.
    """
    # A challenge is nameable as "Category/Title" or by slug, and a row in this
    # file shadows the database copy of itself.
    by_key: dict[str, UUID | _Planned] = {}
    for challenge in lookups.by_slug.values():
        by_key[challenge.slug.lower()] = challenge.id
    for (category_id, title), challenge in lookups.by_title.items():
        by_key[f"{lookups.category_names[category_id].lower()}/{title}"] = challenge.id
    for entry in planned:
        by_key[_self_key(entry)] = entry
        if entry.row.get("slug"):
            by_key[entry.row["slug"].lower()] = entry

    #: line -> the lines it requires, for the cycle check below.
    edges: dict[int, set[int]] = {}

    for entry in planned:
        if not entry.unlocks:
            continue
        for index, requirement in enumerate(entry.unlocks):
            target = requirement.pop("challenge", None)
            if target is None:
                continue

            found = by_key.get(target.lower())
            if found is None:
                report.errors.append(
                    RowError(
                        entry.line,
                        "unlocks",
                        f"[{index}] names {target!r}, which is in neither the file "
                        "nor the platform.",
                    )
                )
                continue

            is_self = found is entry or (
                not isinstance(found, _Planned)
                and entry.existing is not None
                and found == entry.existing.id
            )
            if is_self:
                report.errors.append(
                    RowError(entry.line, "unlocks", f"[{index}] requires this challenge.")
                )
                continue

            if isinstance(found, _Planned):
                # No id yet if this row creates it, so the edge is carried by
                # line number and resolved once the apply pass has run.
                requirement["_pending_line"] = found.line
                edges.setdefault(entry.line, set()).add(found.line)
            else:
                requirement["required_challenge_id"] = found

    if report.errors:
        return

    cycle = _find_cycle(edges)
    if cycle:
        lines = {entry.line: entry for entry in planned}
        names = " → ".join(
            f"{lines[line].category.name}/{lines[line].row['title']}" for line in cycle
        )
        report.errors.append(
            RowError(
                cycle[0],
                "unlocks",
                f"These challenges require each other, so none could ever unlock: {names}.",
            )
        )


def _self_key(entry: _Planned) -> str:
    """How a row names itself, so another row can require it."""
    return f"{entry.category.name.lower()}/{entry.row['title'].lower()}"


def _find_cycle(graph: dict[int, set[int]]) -> list[int] | None:
    """Depth-first, returning the first cycle found so the error can name it."""
    colour: dict[int, int] = {}
    stack: list[int] = []

    def visit(node: int) -> list[int] | None:
        colour[node] = 1
        stack.append(node)
        for neighbour in graph.get(node, ()):
            if colour.get(neighbour) == 1:
                return stack[stack.index(neighbour) :] + [neighbour]
            if colour.get(neighbour, 0) == 0:
                found = visit(neighbour)
                if found:
                    return found
        stack.pop()
        colour[node] = 2
        return None

    for node in graph:
        if colour.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return None


# --------------------------------------------------------------------------
# JSON cells
# --------------------------------------------------------------------------


def _json_cell(row: dict[str, str], column: str) -> tuple[list[Any] | None, tuple[str, str] | None]:
    """Blank, or a JSON array. A bare object counts as a one-element array — a
    single hint should not need brackets."""
    raw = row.get(column, "")
    if not raw:
        return None, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, (column, f"is not valid JSON: {exc.msg} at position {exc.pos}.")
    if isinstance(parsed, dict):
        return [parsed], None
    if not isinstance(parsed, list):
        return None, (column, "must be a JSON array (or a single JSON object).")
    return parsed, None


def _parse_flags(
    row: dict[str, str],
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    """The answer rules a submission is checked against — any one may match."""
    simple = row.get("flag", "")
    raw, problem = _json_cell(row, "flags")
    if problem:
        return None, problem

    if simple and raw is not None:
        return None, (
            "flags",
            "Use `flag` or `flags`, not both — they are two answers to one question.",
        )
    if simple:
        return [
            {
                "match_type": MatchType.CASE_INSENSITIVE,
                "value": simple,
                "options": {},
                "label": None,
            }
        ], None
    if raw is None:
        return None, None

    rules: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        # A bare string is the common case; spelling it out in full would make
        # the ordinary file unreadable.
        if isinstance(item, str):
            item = {"value": item}
        if not isinstance(item, dict):
            return None, ("flags", f"[{index}] must be a string or an object.")

        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            return None, ("flags", f"[{index}] needs a non-empty `value`.")

        try:
            match_type = MatchType(str(item.get("type", MatchType.CASE_INSENSITIVE.value)).lower())
        except ValueError:
            return None, (
                "flags",
                f"[{index}] type {item.get('type')!r} is not one of: "
                + ", ".join(m.value for m in MatchType),
            )

        options = item.get("options", {})
        if not isinstance(options, dict):
            return None, ("flags", f"[{index}] `options` must be an object.")

        try:
            # Compiled and range-checked now rather than at 09:00 on event day,
            # when a bad pattern is a challenge silently refusing every answer.
            answer_service.validate_rule(match_type, value, options)
        except answer_service.InvalidAnswerRule as exc:
            return None, ("flags", f"[{index}] {exc.message}")

        label = item.get("label")
        if label is not None and not isinstance(label, str):
            return None, ("flags", f"[{index}] `label` must be text.")

        rules.append({"match_type": match_type, "value": value, "options": options, "label": label})
    return rules, None


def _parse_hints(
    row: dict[str, str],
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    raw, problem = _json_cell(row, "hints")
    if problem or raw is None:
        return None, problem

    hints: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, ("hints", f"[{index}] must be an object.")

        title, body = item.get("title"), item.get("body")
        if not isinstance(title, str) or not title.strip():
            return None, ("hints", f"[{index}] needs a non-empty `title`.")
        if not isinstance(body, str) or not body.strip():
            return None, ("hints", f"[{index}] needs a non-empty `body`.")

        cost = item.get("cost", 0)
        if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
            return None, ("hints", f"[{index}] `cost` must be a whole number of XP, or zero.")

        requires = item.get("requires")
        if requires is not None:
            if not isinstance(requires, int) or isinstance(requires, bool):
                return None, (
                    "hints",
                    f"[{index}] `requires` must be the index of an earlier hint.",
                )
            if not 0 <= requires < index:
                # Forward and self references both make a hint that can never
                # unlock, which is worse than no ladder at all.
                return None, (
                    "hints",
                    f"[{index}] `requires` must point at an *earlier* hint in this list.",
                )

        available_after = item.get("available_after")
        if available_after is not None:
            if not isinstance(available_after, str):
                return None, ("hints", f"[{index}] `available_after` must be an ISO timestamp.")
            try:
                available_after = datetime.fromisoformat(available_after)
            except ValueError:
                return None, (
                    "hints",
                    f"[{index}] {item['available_after']!r} is not an ISO timestamp.",
                )

        hints.append(
            {
                "title": title.strip(),
                "body": body,
                "cost": cost,
                "requires": requires,
                "available_after": available_after,
            }
        )
    return hints, None


def _parse_unlocks(
    row: dict[str, str], lookups: "_Lookups"
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    """Requirement rows, with challenge references left unresolved.

    Resolution happens once every row is planned — see :func:`_resolve_unlocks` —
    so a prerequisite may sit further down the file than the challenge it gates.
    """
    raw, problem = _json_cell(row, "unlocks")
    if problem or raw is None:
        return None, problem

    requirements: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, ("unlocks", f"[{index}] must be an object.")

        try:
            requirement_type = RequirementType(str(item.get("type", "")).lower())
        except ValueError:
            return None, (
                "unlocks",
                f"[{index}] type {item.get('type')!r} is not one of: "
                + ", ".join(t.value for t in RequirementType if t not in UNAUTHORABLE_REQUIREMENTS),
            )
        if requirement_type in UNAUTHORABLE_REQUIREMENTS:
            return None, ("unlocks", f"[{index}] {requirement_type.value} is not authorable.")

        expected = REQUIREMENT_FIELDS[requirement_type]
        supplied = {k for k in item if k not in {"type", "group"}}
        if extra := supplied - expected:
            return None, (
                "unlocks",
                f"[{index}] a {requirement_type.value} requirement never reads: "
                + ", ".join(sorted(extra)),
            )
        if missing := expected - supplied:
            return None, (
                "unlocks",
                f"[{index}] a {requirement_type.value} requirement needs: "
                + ", ".join(sorted(missing)),
            )

        built: dict[str, Any] = {"requirement_type": requirement_type}

        if "threshold" in expected:
            threshold = item.get("threshold")
            if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
                return None, ("unlocks", f"[{index}] `threshold` must be a positive whole number.")
            if requirement_type == RequirementType.PERCENT_IN_CATEGORY and threshold > 100:
                return None, ("unlocks", f"[{index}] a percentage cannot be above 100.")
            built["threshold"] = threshold

        if "category" in expected:
            category = lookups.categories.get(str(item.get("category", "")).lower())
            if category is None:
                return None, ("unlocks", f"[{index}] no category named {item.get('category')!r}.")
            built["required_category_id"] = category.id

        if "skill" in expected:
            skill_id = lookups.skills.get(str(item.get("skill", "")).lower())
            if skill_id is None:
                return None, ("unlocks", f"[{index}] no skill named {item.get('skill')!r}.")
            built["required_skill_id"] = skill_id

        if "challenge" in expected:
            target = item.get("challenge")
            if not isinstance(target, str) or not target.strip():
                return None, ("unlocks", f"[{index}] `challenge` must name a challenge.")
            built["challenge"] = target.strip()

        group = item.get("group")
        if group is not None:
            if not isinstance(group, int) or isinstance(group, bool):
                return None, ("unlocks", f"[{index}] `group` must be a whole number.")
            built["alternative_group"] = group

        requirements.append(built)
    return requirements, None


# --------------------------------------------------------------------------
# Scalar column checks
# --------------------------------------------------------------------------


def _enum_check(enum_type: type) -> Any:
    def check(value: str) -> str | None:
        if not value:
            return None
        try:
            enum_type(value.lower())
        except ValueError:
            return f"{value!r} is not one of: " + ", ".join(m.value for m in enum_type)
        return None

    return check


def _timestamp_check(value: str) -> str | None:
    if not value:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return f"{value!r} is not an ISO timestamp."
    return None


def _positive_check(value: str) -> str | None:
    if not value:
        return None
    if not value.isdigit() or int(value) < 1:
        return f"{value!r} is not a positive whole number."
    return None


def _threshold_check(value: str) -> str | None:
    if not value:
        return None
    if not value.isdigit() or int(value) < 2:
        # The decay curve divides by the threshold.
        return f"{value!r} is not a whole number of 2 or more."
    return None


def _validate_ladder_level(
    row: dict[str, str], line: int, seen_rungs: dict[int, int]
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


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------


async def _apply(db: AsyncSession, entry: _Planned) -> None:
    row, category = entry.row, entry.category
    xp_base = get_settings().xp_base
    challenge = entry.existing

    if challenge is None:
        challenge = Challenge(
            title=row["title"],
            slug=row.get("slug") or await _unique_slug(db, row["title"]),
            category_id=category.id,
        )
        db.add(challenge)

    challenge.title = row["title"]
    challenge.category_id = category.id
    challenge.body = row.get("description", "")
    challenge.difficulty = entry.difficulty

    # XP is the file's number (spec 040). Difficulty only fills a blank cell on a
    # challenge that has no value yet — it never overwrites one, so re-importing
    # with an edited difficulty cannot silently re-price the event.
    if row.get("xp"):
        challenge.initial_points = int(row["xp"])
    elif challenge.id is None:
        challenge.initial_points = points_for(entry.difficulty, xp_base)

    if row.get("minimum_xp"):
        challenge.minimum_points = int(row["minimum_xp"])
    elif row.get("xp") or challenge.id is None:
        challenge.minimum_points = default_minimum_xp(challenge.initial_points)

    if row.get("scoring"):
        challenge.scoring = ScoringMode(row["scoring"].lower())
    elif challenge.id is None:
        challenge.scoring = ScoringMode.STATIC

    if row.get("decay_threshold"):
        challenge.decay_threshold = int(row["decay_threshold"])
    if row.get("decay_basis"):
        challenge.decay_basis = DecayBasis(row["decay_basis"].lower())
    if row.get("pre_release_state"):
        challenge.pre_release_state = PreReleaseState(row["pre_release_state"].lower())

    challenge.state = (
        ChallengeState(row["state"].lower())
        if row.get("state")
        else (challenge.state if challenge.id else ChallengeState.DRAFT)
    )
    challenge.max_attempts = int(row["max_attempts"]) if row.get("max_attempts") else None
    challenge.ai_ladder_level = int(row["ai_ladder_level"]) if row.get("ai_ladder_level") else None
    challenge.boss_tier = entry.boss_tier
    challenge.release_at = (
        datetime.fromisoformat(row["release_at"]) if row.get("release_at") else None
    )
    if entry.container_template_id is not None:
        challenge.container_template_id = entry.container_template_id

    await db.flush()

    if entry.flags is not None:
        await _sync_answers(db, challenge, entry.flags)
    if entry.hints is not None:
        await _sync_hints(db, challenge, entry.hints)
    if entry.skill_ids is not None:
        await db.execute(
            ChallengeSkill.__table__.delete().where(ChallengeSkill.challenge_id == challenge.id)
        )
        for skill_id in entry.skill_ids:
            db.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill_id))

    entry.existing = challenge


async def _sync_answers(
    db: AsyncSession, challenge: Challenge, rules: list[dict[str, Any]]
) -> None:
    """Reconcile by position rather than replacing the set.

    ``submission.matched_answer_id`` points at these rows. Deleting and recreating
    every rule on every import would blank that link across the whole submission
    log for a one-character fix to a flag.
    """
    current = list(
        (
            await db.execute(
                select(ChallengeAnswer)
                .where(ChallengeAnswer.challenge_id == challenge.id)
                .order_by(ChallengeAnswer.display_order)
            )
        )
        .scalars()
        .all()
    )

    for index, rule in enumerate(rules):
        if index < len(current):
            answer = current[index]
        else:
            answer = ChallengeAnswer(challenge_id=challenge.id)
            db.add(answer)
        answer.match_type = rule["match_type"]
        answer.value = rule["value"]
        answer.options = rule["options"]
        answer.label = rule["label"]
        answer.display_order = index

    for surplus in current[len(rules) :]:
        await db.delete(surplus)


async def _sync_hints(db: AsyncSession, challenge: Challenge, hints: list[dict[str, Any]]) -> None:
    """Also by position, so editing a hint's text keeps the purchases against it."""
    current = list(
        (
            await db.execute(
                select(Hint).where(Hint.challenge_id == challenge.id).order_by(Hint.display_order)
            )
        )
        .scalars()
        .all()
    )

    written: list[Hint] = []
    for index, spec in enumerate(hints):
        if index < len(current):
            hint = current[index]
        else:
            hint = Hint(challenge_id=challenge.id)
            db.add(hint)
        hint.title = spec["title"]
        hint.body = spec["body"]
        hint.cost = spec["cost"]
        hint.display_order = index
        hint.available_after = spec["available_after"]
        # Cleared first: a ladder rung the file dropped must not survive.
        hint.prerequisite_hint_id = None
        written.append(hint)

    for surplus in current[len(hints) :]:
        await db.delete(surplus)
    await db.flush()

    # A second pass, because a rung's target needs an id before it can be named.
    for index, spec in enumerate(hints):
        if spec["requires"] is not None:
            written[index].prerequisite_hint_id = written[spec["requires"]].id


async def _sync_unlocks(
    db: AsyncSession,
    challenge: Challenge,
    requirements: list[dict[str, Any]],
    created_ids: dict[int, UUID],
) -> None:
    """Replaced wholesale — a requirement carries no history worth keeping."""
    await db.execute(
        UnlockRequirement.__table__.delete().where(UnlockRequirement.challenge_id == challenge.id)
    )
    for requirement in requirements:
        fields = dict(requirement)
        pending = fields.pop("_pending_line", None)
        if pending is not None:
            # A challenge this same file created; it has an id only now.
            fields["required_challenge_id"] = created_ids[pending]
        db.add(UnlockRequirement(challenge_id=challenge.id, **fields))


async def _unique_slug(db: AsyncSession, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-") or "challenge"
    slug = base
    suffix = 2
    while await db.scalar(select(Challenge.id).where(Challenge.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


@dataclass
class _Lookups:
    """Everything the file is validated against, read once.

    242 rows each resolving their own category and skills would be 242 round
    trips per column; this is one query per table.
    """

    categories: dict[str, Category]
    category_names: dict[UUID, str]
    #: Canonical spellings, for the error an unknown one produces.
    zone_names: list[str]
    skills: dict[str, UUID]
    by_title: dict[tuple[UUID, str], Challenge]
    by_slug: dict[str, Challenge]
    templates: dict[str, list[UUID]]
    hints: dict[UUID, list[tuple[Hint, int]]]
    #: Whatever already holds a zone's boss slot, so a collision can name it.
    bosses: list[Challenge]

    @classmethod
    async def load(cls, db: AsyncSession) -> "_Lookups":
        categories = list((await db.execute(select(Category))).scalars().all())
        keyed: dict[str, Category] = {}
        for category in categories:
            # Name *and* slug both resolve, so a hand-edited file is forgiving.
            keyed[category.name.lower()] = category
            keyed[category.slug.lower()] = category

        challenges = list((await db.execute(select(Challenge))).scalars().all())

        templates: dict[str, list[UUID]] = {}
        for template_id, name in (
            await db.execute(select(ContainerTemplate.id, ContainerTemplate.name))
        ).all():
            templates.setdefault(name.lower(), []).append(template_id)

        unlock_counts = dict(
            (
                await db.execute(
                    select(HintUnlock.hint_id, func.count()).group_by(HintUnlock.hint_id)
                )
            ).all()
        )
        hints: dict[UUID, list[tuple[Hint, int]]] = {}
        for hint in (await db.execute(select(Hint).order_by(Hint.display_order))).scalars().all():
            hints.setdefault(hint.challenge_id, []).append((hint, unlock_counts.get(hint.id, 0)))

        return cls(
            categories=keyed,
            category_names={c.id: c.name for c in categories},
            zone_names=[c.name for c in categories],
            skills={
                name.lower(): skill_id
                for skill_id, name in (await db.execute(select(Skill.id, Skill.name))).all()
            },
            by_title={(c.category_id, c.title.lower()): c for c in challenges},
            by_slug={c.slug.lower(): c for c in challenges},
            templates=templates,
            hints=hints,
            bosses=[c for c in challenges if c.boss_tier is not None],
        )


async def _answers_by_challenge(db: AsyncSession) -> dict[UUID, list[ChallengeAnswer]]:
    grouped: dict[UUID, list[ChallengeAnswer]] = {}
    for answer in (
        (await db.execute(select(ChallengeAnswer).order_by(ChallengeAnswer.display_order)))
        .scalars()
        .all()
    ):
        grouped.setdefault(answer.challenge_id, []).append(answer)
    return grouped


async def _hints_by_challenge(db: AsyncSession) -> dict[UUID, list[Hint]]:
    grouped: dict[UUID, list[Hint]] = {}
    for hint in (await db.execute(select(Hint).order_by(Hint.display_order))).scalars().all():
        grouped.setdefault(hint.challenge_id, []).append(hint)
    return grouped


async def _unlocks_by_challenge(db: AsyncSession) -> dict[UUID, list[UnlockRequirement]]:
    grouped: dict[UUID, list[UnlockRequirement]] = {}
    for requirement in (
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.challenge_id.is_not(None))
            )
        )
        .scalars()
        .all()
    ):
        grouped.setdefault(requirement.challenge_id, []).append(requirement)
    return grouped


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


async def _id_names(db: AsyncSession) -> dict[UUID, str]:
    """Category and skill names by id, for writing requirements back out."""
    names: dict[UUID, str] = {}
    for category_id, name in (await db.execute(select(Category.id, Category.name))).all():
        names[category_id] = name
    for skill_id, name in (await db.execute(select(Skill.id, Skill.name))).all():
        names[skill_id] = name
    return names


# --------------------------------------------------------------------------
# Export serialisation
# --------------------------------------------------------------------------


def _simple_flag(rules: list[ChallengeAnswer]) -> str:
    """The one shape that fits the plain `flag` column: a single case-insensitive
    rule with nothing configured on it. Anything else has to go out as JSON."""
    if len(rules) != 1:
        return ""
    rule = rules[0]
    if rule.match_type != MatchType.CASE_INSENSITIVE or rule.options or rule.label:
        return ""
    return rule.value


def _dump_flags(rules: list[ChallengeAnswer]) -> str:
    out = []
    for rule in rules:
        item: dict[str, Any] = {"type": rule.match_type.value, "value": rule.value}
        if rule.options:
            item["options"] = rule.options
        if rule.label:
            item["label"] = rule.label
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


def _dump_hints(hints: list[Hint]) -> str:
    if not hints:
        return ""
    positions = {hint.id: index for index, hint in enumerate(hints)}
    out = []
    for hint in hints:
        item: dict[str, Any] = {"title": hint.title, "body": hint.body, "cost": hint.cost}
        if hint.prerequisite_hint_id in positions:
            item["requires"] = positions[hint.prerequisite_hint_id]
        if hint.available_after:
            item["available_after"] = hint.available_after.isoformat()
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


def _dump_unlocks(
    requirements: list[UnlockRequirement],
    titles: dict[UUID, str],
    names: dict[UUID, str],
) -> str:
    out = []
    for requirement in requirements:
        if requirement.requirement_type in UNAUTHORABLE_REQUIREMENTS:
            # Never written out: the export is also the file that gets re-imported,
            # and a secret route that round-trips is a secret route in a spreadsheet.
            continue
        item: dict[str, Any] = {"type": requirement.requirement_type.value}
        if requirement.required_challenge_id:
            item["challenge"] = titles.get(
                requirement.required_challenge_id, str(requirement.required_challenge_id)
            )
        if requirement.required_category_id:
            item["category"] = names.get(requirement.required_category_id, "")
        if requirement.required_skill_id:
            item["skill"] = names.get(requirement.required_skill_id, "")
        if requirement.threshold is not None:
            item["threshold"] = requirement.threshold
        if requirement.alternative_group is not None:
            item["group"] = requirement.alternative_group
        out.append(item)
    return json.dumps(out, ensure_ascii=False) if out else ""
