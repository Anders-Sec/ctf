# Spec 040 — Full-Fidelity Challenge CSV

Status: **approved** (2026-09-14)
Phase: 2/3 boundary (tooling)
Supersedes the column set and the XP rule in: 026 (challenge CSV)
Depends on: 003 (answer rules), 004 (hints), 017 (unlock requirements), 031 (boss tiers), 033 (the AI ladder)

Spec 026 built the spreadsheet round-trip for a human filling in 242 rows by
hand, and deliberately kept the file narrow: one flag, no hints, no boss, no
prerequisites, XP derived from difficulty. Everything it left out has to be
re-done by hand in the admin UI after every import.

The authoring model has changed. A Claude session now writes the file, so the
file no longer has to be pleasant to type — it has to be **complete**. An import
should land a challenge in its finished state, with nothing left to patch up in
the editor afterwards.

Three changes, together:

1. **Every authored property of a challenge is a column**, including the ones
   that are lists — flags, hints, prerequisites — carried as JSON in a single
   cell.
2. **XP is set per challenge.** Difficulty stops deriving it and becomes what its
   name says: a label describing how hard the thing is.
3. **The vocabulary is XP** — in the CSV and in what a player reads. A challenge
   does not have points and a solve does not award a score. Internal names and
   database columns are left alone; see §1a for exactly where the line falls.

## 1. XP is per challenge

Today `difficulty` *derives* `initial_points`, `minimum_points` and the scoring
mode, in the editor and on import alike (spec 018's economy). That goes away.

| | Before | After |
| --- | --- | --- |
| the value | `DIFFICULTY_MODIFIER[difficulty] * xp_base` | the `xp` column / an editor field |
| the floor | 40% of the derived ceiling | the `minimum_xp` column, blank = 40% of `xp` |
| `scoring` | dynamic for the top two tiers, else static | the `scoring` column, blank = `static` |
| `difficulty` | the economy's input | a descriptive label; nothing reads it for value |

The difficulty table is **not deleted** — it is demoted to the source of the
template's suggested numbers, the fallback for a blank `xp` cell, and the seed for
sample data. The 018 economy therefore still happens by default for anyone who
fills the template in as-is, but it is a starting value in a cell rather than an
invariant in code.

Changing a challenge's difficulty after the fact no longer moves its value. That
is the point: an admin relabelling something "hard" mid-event should not silently
change what it pays.

**The admin editor changes with it.** The create and edit forms gain an **XP**
field and a **minimum XP** field, and changing `difficulty` stops rewriting
either. The XP field is pre-filled from the difficulty's suggestion when a
challenge is created, so the form stays quick — but it is a value the admin can
see and overwrite, not a number computed behind them. Leaving the editor deriving
XP while the CSV does not would give the same challenge two different values
depending on which door it came through.

## 1a. The rename — two surfaces only

The vocabulary change is **the CSV workflow and what a player reads**. Internal
identifiers, database columns and API field names are explicitly *not* in scope:
renaming them is churn against a working system with one frontend, and no player
ever sees them.

**In scope — the CSV.** The column is `xp`. `minimum_xp` alongside it. The
template, the export, the import report and the admin CSV panel all say XP.

**In scope — player-facing copy.** Five places still say points or score where
they mean a challenge's XP:

| Where | Before | After |
| --- | --- | --- |
| [`challenges.py:195`](../backend/app/api/routes/challenges.py#L195) | `Correct. 420 points.` | `Correct. 420 XP.` |
| [`ChallengeDetailPage.tsx:82`](../frontend/src/routes/ChallengeDetailPage.tsx#L82) | `420 points · hard` | `420 XP · hard` |
| [`HintList.tsx:71,82`](../frontend/src/components/HintList.tsx#L71) | `Spend 25 points` / `Unlock — 25 points` | `Spend 25 XP` / `Unlock — 25 XP` |
| [`ChallengesPage.tsx:101`](../frontend/src/routes/ChallengesPage.tsx#L101) | aria-label `Your score` | `Your XP` |
| [`PartyPage.tsx:348`](../frontend/src/routes/PartyPage.tsx#L348) | `your score goes with you` | `your XP goes with you` |

The scoreboard already says **XP** in its column headers, so the board needs no
change — these five are the stragglers.

**Out of scope, deliberately:**

- `challenge.initial_points` / `minimum_points` and every other database column.
  No migration, no data change.
- `points_for()`, `minimum_points_for()`, `MINIMUM_POINTS_FRACTION`,
  `points_awarded`, `current_value` and the rest of the API field names. The CSV
  layer maps `xp` → `initial_points` at the boundary, which is what a CSV layer is
  for.
- `ability_score` / `AbilityScore` — a D&D stat block genuinely has ability
  *scores*, and it is not a rival currency.
- `hint.cost` — already currency-neutral; only its **copy** changes, above.
- The scoreboard, `ScoreAdjustment` and the admin ops override page. Staff-facing,
  and a separate change if it is ever wanted — see §11.

## 2. The columns

Blank always means "leave it alone": on a new challenge, the default below; on an
existing one, whatever it already has. Only `category`, `title` and `difficulty`
are required — every other column can be left blank and the row still imports.

### Identity and content

| Column | Notes |
| --- | --- |
| `category` | Required. Name or slug of an existing category. Never created. |
| `title` | Required. Unique within the category. Blank = the row is skipped. |
| `slug` | Optional. When given it is the match key, so a title can be **renamed** without the import creating a second challenge. Blank = derived from the title, as now. |
| `difficulty` | Required. One of the six ladder values. Descriptive only. |
| `description` | The challenge body. |

### XP

| Column | Default when blank |
| --- | --- |
| `xp` | The difficulty's suggested XP — the only thing left reading the 018 table |
| `minimum_xp` | `max(1, xp * 0.4)`. The floor decay stops at; ignored when `scoring` is `static` |
| `scoring` | `static`. `dynamic` is available and is how a challenge decays |
| `decay_threshold` | 40 |
| `decay_basis` | `players` |

### Availability

| Column | Default when blank |
| --- | --- |
| `state` | `draft` (026's decision stands — 242 challenges going live in one request is hard to undo) |
| `release_at` | no schedule |
| `pre_release_state` | `hidden` |
| `max_attempts` | unlimited |

### Relations

| Column | Shape |
| --- | --- |
| `flag` | The simple case: one case-insensitive answer. |
| `flags` | JSON array. Full fidelity. Mutually exclusive with `flag`. |
| `hints` | JSON array. |
| `unlocks` | JSON array of unlock requirements. |
| `skills` | Semicolon-separated names, as now. Already expressive enough; not worth JSON. |
| `boss_tier` | One of the six tiers, or blank for "not a boss". |
| `container_template` | Template name, matched case-insensitively. Never created. |
| `ai_ladder_level` | 0–5, unique across the file and the database. As now. |

## 3. The JSON cells

One rule for all three: **blank, or a JSON array**. A bare object is accepted as
a one-element array, because a single hint should not need brackets. Errors name
the row, the column, *and the index within the array* — `row 14, hints[2]: cost
must be a whole number` — since "invalid JSON" against a 242-row file is the same
uselessness 026 was written to avoid.

The double-quote doubling CSV requires inside a quoted cell is the writer's and
reader's problem, not the author's. Both ends use the `csv` module.

### `flags`

```json
[
  "443",
  {"type": "regex", "value": "^ctf\\{[a-f0-9]{8}\\}$", "options": {"ignore_case": true}, "label": "any wrapper"},
  {"type": "set", "value": "CVE-2021-1, CVE-2021-2", "options": {"case_insensitive": true}}
]
```

- A **bare string** entry means `{"type": "case_insensitive", "value": "..."}`.
  The common case stays one word long.
- `type` — any `MatchType`: `exact`, `case_insensitive`, `regex`, `numeric`,
  `set`, `any_of`. Defaults to `case_insensitive`.
- `value` — required.
- `options` — the per-type settings that already exist (`tolerance`, `min`/`max`,
  `separator`, `ordered`, `ignore_case`, `strip_whitespace`, `timeout_ms`).
  Validated by the existing `answers.validate_rule`, so a pattern that will not
  compile is refused at import rather than at 09:00 on event day.
- `label` — optional admin-facing note.
- Array order becomes `display_order`. A submission is correct if **any** rule
  matches, which is what "more than one flag" means here.

`flag` and `flags` in the same row is refused rather than merged — two sources
for one fact.

### `hints`

```json
[
  {"title": "Where to look", "body": "The response headers say more than the page does.", "cost": 25},
  {"title": "The technique", "body": "...", "cost": 50, "requires": 0, "available_after": "2026-10-02T09:00:00Z"}
]
```

- `title`, `body` required; `cost` defaults to 0 (a free hint is legitimate).
- `requires` — the **zero-based index of an earlier hint in the same array**,
  becoming `prerequisite_hint_id`. Indexes rather than ids, because the file has
  no ids and a hint ladder is almost always "the one before this one". Forward or
  self references are refused.
- `available_after` — optional ISO timestamp, independent of `requires`.
- Array order becomes `display_order`.

### `unlocks`

```json
[
  {"type": "challenge_solved", "challenge": "Networking/Port of Call"},
  {"type": "percent_in_category", "category": "networking", "threshold": 50, "group": 1},
  {"type": "player_level", "threshold": 4, "group": 1}
]
```

- `type` — any `RequirementType` except `ai_ladder_leak`, which is the ladder's
  secret route and is set by 033's own seed, not authored.
- `challenge` — `Category/Title`, or a slug. **Forward references are allowed**:
  requirements resolve after every row in the file is planned, so a prerequisite
  may appear later in the file than the challenge it gates.
- `category`, `skill` — by name or slug.
- `threshold` — the XP, level, count or percent the type reads.
- `group` — `alternative_group`. Rows sharing a group are OR'd; groups and
  ungrouped rows AND together.
- A requirement carrying a field its type never reads is refused, matching what
  the admin endpoint already does.

Zone-level requirements are **not** here. This is a challenge file; a category's
own gating is edited in the platform.

## 4. Sync semantics

The flat columns overwrite. The list columns need a rule, and the rule is the
same shape as 026's: **blank leaves the existing set alone; a value makes the
file authoritative for that set.**

| Column | Non-blank means |
| --- | --- |
| `flags` / `flag` | Reconciled **by position**: positions in both are updated in place, new positions created, surplus positions deleted. Position rather than wholesale replace, so `submission.matched_answer_id` survives an edit to a flag's text. |
| `hints` | Reconciled by position. A surplus hint **with unlocks** is refused with a row error naming it, rather than deleted — someone paid for that. A surplus hint nobody bought is deleted. |
| `unlocks` | Replaced. Requirements carry no history worth keeping. |
| `skills` | Replaced, as now. |

An empty JSON array `[]` is the explicit "clear this set" — distinct from blank,
which is "not mentioned". That distinction is the whole reason an empty array is
allowed at all.

Import still **never deletes a challenge**. Omission is not a delete.

## 5. Template and export

- **Template** — unchanged in shape: every category, 11 rows, `category` and
  `difficulty` pre-filled. It now also pre-fills **`xp`** with the ladder's number
  (50/100/150/200/250/500), so the 1,900-per-area, 41,800-overall economy still
  lands for anyone who fills the file in without touching the column.
- **Export** — emits every column, so export → edit → import round-trips with
  nothing lost. A challenge whose answer set is exactly one case-insensitive rule
  with no options and no label exports through the plain `flag` column; anything
  else exports through `flags`. The common file stays readable.

## 6. Backwards compatibility

A spec-026 file (11 columns) still imports. Absent columns are read as blank, and
the header requirement stays `category`, `title`, `difficulty`.

The one thing that does **not** carry over is the `points` column. A file whose
header still says `points` is **refused with a message naming the rename** —
"`points` is now `xp`" — rather than silently ignored. Ignoring it would read
every deliberate override as a blank and quietly reset those challenges to their
difficulty default, which is the kind of silent data loss a 242-row file makes
impossible to notice. There is no alias: the authoring session regenerates its
file against the new contract, so an alias would be a code path with no reader.

The other behaviour change for an old file is that a blank `xp` now yields the
difficulty's suggested value as a stored number rather than a derived one — the
same number, no longer recomputed when difficulty changes.

## 7. Edge cases

- **Two rows claiming the same boss slot in one zone** — refused up front, naming
  both lines, since the partial unique index would otherwise fail halfway through
  the apply and break the all-or-nothing promise. Same for a row claiming a zone's
  slot when a challenge outside the file already holds it.
- **A `regex` flag that will not compile** — refused, naming the row and the index.
- **A hint with `requires` pointing forward, or at itself** — refused.
- **An unlock naming a challenge in neither the file nor the database** — refused.
- **An unlock cycle** (A requires B requires A) — refused; a cycle makes both
  challenges permanently unreachable.
- **An ambiguous `container_template` name** — refused naming the count, since
  template names are not unique.
- **Deleting an answer rule a past submission matched** — allowed; the existing
  `ON DELETE SET NULL` drops the link and the submission log keeps the attempt.
- **A JSON cell that is valid JSON but not an array or object** — refused with
  the column named, not a bare parser message.

## 8. Testing

Carrying forward 026's suite, plus:

- A template row's `xp` matches the difficulty's suggested XP, and the non-Intro
  spread still totals 1,900.
- `xp` imports as `challenge.xp` and is **not** overwritten by difficulty.
- Changing only `difficulty` on re-import leaves `xp` untouched.
- A blank `xp` on a new challenge takes the difficulty's suggested value.
- Blank `scoring` imports as `static`; `dynamic` imports as `dynamic` and decays
  toward `minimum_xp`.
- A file whose header still says `points` is refused, naming the rename.
- The five player-facing strings say XP, not points or score.
- The admin editor creates and updates a challenge with an explicit XP, and
  changing difficulty through the editor does not move it.
- `flags` with four rules creates four answers in array order; each match type
  resolves as its resolver does.
- A bare-string `flags` entry is a case-insensitive rule.
- `flag` and `flags` together is refused.
- Editing a flag's text by position keeps the answer's id.
- `hints` creates hints with costs, order and the `requires` ladder.
- A re-import dropping a hint that has unlocks is refused; dropping an unbought
  one succeeds.
- `unlocks` resolves a forward reference, and a cycle is refused.
- `boss_tier` sets the tier; a second boss in the same zone is refused naming the
  first.
- `[]` clears a set; blank does not.
- Export → import is a no-op for a challenge using every column.
- A 026-era 11-column file still imports.
- Only admins may import; only staff may export.

## 9. Non-goals

- **Artifacts.** The bytes live in object storage; a CSV cell cannot carry them,
  and a filename with nothing behind it is worse than an empty column.
- **Map coordinates.** Spec 027 owns layout portability and has its own file.
- **Creating categories, skills or container templates.** The CSV references
  them; inventing them from a typo is exactly what 026 refused to do.
- **Zone-level unlock requirements.**
- **Achievements.** Code-registered triggers over player history, not challenge
  properties.
- **Deleting challenges by omission.**

## 10. Decisions (2026-09-14)

1. **Blank `xp` falls back to the difficulty's suggested XP.** Not an error. It is
   what keeps the template's economy working out of the box, and it is the only
   remaining thing the 018 difficulty table feeds.
2. **Blank `scoring` is `static`.** Nothing derives dynamic any more. `dynamic`,
   `decay_threshold` and `decay_basis` are all available as columns for a
   challenge that should decay.
3. **The admin editor stops deriving XP** and gains an XP field, pre-filled from
   the difficulty's suggestion on create and never rewritten afterwards.
4. **Artifacts stay in the UI.** Not a CSV concern; the bytes live in MinIO.
5. **The vocabulary is XP, not points or score — in the CSV and in player-facing
   copy only.** Internal identifiers, database columns and API field names stay
   as they are. §1a lists both sides of the line.
6. **`slug` is the match key when present.** A title can be edited and re-imported
   without creating a second challenge, which is what makes a re-generated file
   safe to re-import. `(category, title)` remains the fallback when `slug` is
   blank.

## 11. Follow-up, not in this spec

**The staff-facing score vocabulary.** The admin ops page still has a `Points`
field and a "Score adjustments" heading, and `ScoreAdjustment` is the table behind
them (spec 006). Nobody but staff sees it, so it sits outside this spec's
player-facing line — but it is the one remaining place where a number measured in
XP is labelled points, and it is worth a small copy pass on its own some time.

Note that "scoreboard" as the *name of the board* is very likely the right English
word even when everything on it is XP; the board's own columns already say XP.
