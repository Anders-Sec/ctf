# Spec 044 — Daily Puzzle Challenges (Wordle, Connections, Crossword)

Status: **draft** — awaiting sign-off
Phase: 2/3 boundary (content)
Depends on: 003 (challenges and flags), 015 (XP banking), 017/019 (the board and zones), 041 (the challenge manager)
Amends: 007 (anti-cheat exemptions), 029 (achievement roster), 043 (event reset groups)

The **Hacker Game Show** zone exists but is empty — 11 slots in the CSV template
and a seeded description reading *"Cyber security themed Wordle, Connections
etc"* ([migration 0021](../backend/migrations/versions/0021_seed_event_content.py#L39)).
This spec fills it with three playable games, security-themed, one puzzle per
game per day, **played inside the platform** rather than linked out to a
third-party site.

The whole design rests on one decision: **a puzzle is a challenge.** Not a new
top-level object with its own board, scoreboard and progress model — an ordinary
row in `challenge` that happens to be played rather than answered. Everything the
platform already does to a challenge (scheduled release, locking, the map, the
zone panel, hints, XP banking, achievements, the audit log, deletion rules) it
does to a puzzle for free, and the only genuinely new thing is *how the player
interacts with the description block*.

## 1. What the player sees

A daily puzzle is a normal card on the list and inside the zone panel on the map.
Opening it goes to `/challenges/:id` as everything else does. There, the block
that normally renders `detail.body`
([ChallengeDetailPage.tsx:124](../frontend/src/routes/ChallengeDetailPage.tsx#L124))
renders the game instead, and **the answer box is gone** — there is nothing to
type a flag into, because the game is the only way in.

`body` is still shown above the game when it is set, as the puzzle's framing —
the day's theme, a line of narration. It is not where the puzzle lives.

Hints still work, and still cost XP out of the reward at solve time. A hint on a
Wordle is authored prose ("today's word is something you'd run against a subnet"),
not a mechanical letter reveal — nothing new is needed for that.

## 2. Cadence: one challenge per puzzle, per day

`Wordle — Day 1`, `Connections — Day 1`, `Crossword — Day 1`, then Day 2, and so
on. Three challenges a day, all in the Hacker Game Show zone, each with its own
`release_at` and `pre_release_state = locked`, so tomorrow's puzzle is visible as
a sealed door rather than absent.

The alternative — one challenge per game whose content rotates — was rejected.
`solve` is unique on `(user_id, challenge_id)`, `xp_awarded` is a snapshot banked
once and never recomputed ([play.py:59](../backend/app/models/play.py#L59)), and
the decay curve counts solves per challenge. A rotating challenge breaks all
three and needs a second scoring system running alongside the real one.

### The schedule

Five days, three puzzles a day, fifteen challenges.

| Day | Difficulty | XP each | Day total |
| --- | --- | --- | --- |
| 1 | `very_easy` | 50 | 150 |
| 2 | `easy` | 100 | 300 |
| 3 | `medium` | 150 | 450 |
| 4 | `medium` | 150 | 450 |
| 5 | `hard` | 200 | 600 |
| | | | **1,950** |

Which lands the zone on spec 018's target of roughly 2,000 XP per category. All
three of a day's puzzles carry the same difficulty and the same value — which
game you find easiest is a matter of taste, not of tier.

These numbers are not an override of anything: `DIFFICULTY_MODIFIER × XP_BASE`
([challenge.py:76](../backend/app/models/challenge.py#L76), `xp_base = 10`)
already suggests 50 / 100 / 150 / 200 for these four tiers. Leaving the XP field
blank in the editor produces this table exactly, so the ladder is the platform's
own default rather than a set of hand-typed numbers to keep in step.

Puzzle challenges are **statically scored**. A daily that everyone plays would
otherwise decay to its floor by lunchtime on day one — which punishes exactly the
players this zone is meant to welcome, and would quietly dismantle the 1,950
above.

### A note on zone gating

`Codes and Ciphers` and `Crypto` require 25% of Hacker Game Show
([migration 0023](../backend/migrations/versions/0023_seed_progression_graph.py#L44)),
and `percent_in_category` counts *visible* challenges. Because a failed puzzle is
permanently unsolvable (§6), a player who fails several days has a hard ceiling
below 100% in this zone. At 25% across ~15 puzzles that is harmless. **Do not
raise a percent gate on this zone much past 50%** without revisiting this — it is
the one zone where a player can lose access to points through no ongoing fault.

## 3. Data model

Two new tables. Nothing is added to `challenge`.

### `challenge_puzzle` — the authored puzzle

One row per puzzle challenge, `challenge_id` unique, `ON DELETE CASCADE`. A side
table rather than columns on `challenge` because the config is fat JSON that no
list query wants to carry, and because a challenge either has a puzzle or does
not — a nullable relationship, not five nullable columns.

| Column | Notes |
| --- | --- |
| `challenge_id` | Unique FK. The 1:1 is a database guarantee. |
| `kind` | `wordle` \| `connections` \| `crossword`. |
| `config` | JSONB. Kind-specific, validated by a discriminated union on write (§4). **Contains the answers.** |

The config is never sent to a player. Every endpoint that returns puzzle data to
a player returns a derived, answer-free *view* of it — the same discipline as
`body` being withheld server-side for a locked challenge rather than hidden by
the client.

### `puzzle_session` — one player's play

Unique on `(user_id, challenge_id)`, both FKs cascading.

| Column | Notes |
| --- | --- |
| `status` | `in_progress` \| `solved` \| `failed`. Terminal once it leaves `in_progress`. |
| `state` | JSONB. Kind-specific: the guesses so far, the groups found, the letters typed. |
| `moves_used` | Guesses, group attempts, or checks — whichever the kind counts. |
| `started_at`, `finished_at` | `finished_at` set on solve or fail. |

State is server-side because it has to be: the client cannot hold the answer, so
it cannot evaluate a guess, so the server is already in the loop on every move
and may as well own the record. It also means a player can close the tab, switch
to their phone, and pick the crossword back up where they left it.

## 4. The three games

Each kind is one **engine** on the backend — a validator for its config, a
projector to the player-safe view, and a `move` handler — registered against its
`PuzzleKind`. This is deliberately the same shape as the answer-matching registry
([answers.py:51](../backend/app/services/answers.py#L51)): adding a fourth game
is one module and one enum member, not a new endpoint or a new table.

```python
class PuzzleEngine(Protocol):
    def validate(self, config: dict) -> None:            # admin-facing errors
    def view(self, config: dict, session: Session | None) -> dict   # answer-free
    def move(self, config: dict, session: Session, move: dict) -> MoveOutcome
```

```python
@dataclass(frozen=True)
class MoveOutcome:
    state: dict        # replaces the session state
    feedback: dict     # what this move told the player
    solved: bool
    failed: bool
```

### 4.1 Wordle

Six guesses at a five-letter security term. Per-letter feedback: exact, present,
absent — computed server-side, with correct duplicate-letter handling (a repeated
letter is only marked present as many times as it actually occurs).

```json
{
  "answer": "NMAPS",
  "length": 5,
  "max_guesses": 6,
  "extra_words": ["XSRF", "PCAPS"],
  "reveal_on_fail": true
}
```

**Guesses are validated against a word list.** A shipped list of English words of
the puzzle's length, plus `extra_words` on the puzzle, plus the answer itself —
which is always accepted even when it is a term no dictionary carries, because
otherwise an author can write an unsolvable puzzle and not find out.

The list ships as a data file in the backend image and is loaded once into
memory. A rejected guess **does not consume a guess and is not logged as a
submission** — it never reached the puzzle.

The realistic failure mode here is an author choosing a term the list has never
heard of and players being unable to type related words around it. The editor
mitigates it by telling the author, at save time, how many list words share the
answer's length, and by accepting `extra_words` inline.

*Player view:* length, guesses used and remaining, and the per-letter verdict of
every guess so far. Never the answer, until the session is terminal.

### 4.2 Connections

Sixteen tiles, four hidden groups of four, four mistakes allowed.

```json
{
  "groups": [
    {"name": "Ports", "level": 1, "members": ["22", "80", "443", "3389"]},
    {"name": "Hash algorithms", "level": 2, "members": ["MD5", "SHA1", "BCRYPT", "ARGON2"]},
    {"name": "…", "level": 3, "members": ["…"]},
    {"name": "…", "level": 4, "members": ["…"]}
  ],
  "max_mistakes": 4
}
```

Exactly four groups of exactly four, sixteen tiles distinct case-insensitively —
all enforced on save, because a duplicate tile makes a puzzle with two valid
answers. `level` 1–4 is the difficulty colour and the order groups are revealed
in; the four levels must each appear once.

Rules, as the game is normally played — confirmed, not proposed:

- Submitting four tiles that are a group solves that group; it locks to the top.
- Three of four from one group returns **one away** — and costs a mistake.
- Anything else costs a mistake.
- Shuffling and deselecting are free and are not moves.
- The same four tiles submitted twice is rejected without costing a mistake.
- Solving three groups auto-solves the fourth.

*Player view:* the sixteen tiles in a server-chosen shuffled order (stable for
the session), the groups solved so far with their names, and mistakes remaining.
The mapping from tile to group is never sent until the session is terminal.

### 4.3 Crossword mini

A small grid — 5×5 by default, up to 7×7 — with across and down clues.

```json
{
  "width": 5,
  "height": 5,
  "blocks": [[0, 4], [4, 0]],
  "entries": [
    {"direction": "across", "row": 0, "col": 0, "answer": "NMAPS", "clue": "Port scanner, pluralised"}
  ],
  "max_checks": 3
}
```

**Clue numbers are derived, not authored.** The server numbers the grid from its
geometry the way a crossword is numbered, so an author cannot produce a grid
whose numbering contradicts itself. Validation on save: every entry starts at a
numbered cell in its direction and runs to a block or the edge; every crossing
cell agrees between its across and down answers; every non-block cell is covered
by at least one entry.

Checking is **whole-grid, with wrong cells marked.** The player fills what they
can and presses Check; wrong cells are marked wrong — not corrected — and correct
ones are left alone. Three checks, then the session fails.

Marking wrong cells is an oracle, and `max_checks` is what keeps it a small one:
three checks against a 25-cell grid is nowhere near enough to solve it by
bisection, and it is the difference between a puzzle that is satisfying and one
that is a wall.

#### Where the typed letters live

Split by what can and cannot be allowed to go missing.

**Checks used, wrong-cell marks and session status are server-side, always.** If
those lived in the browser, clearing site data would hand you three fresh checks,
and the check limit is the only thing keeping the marking honest. This is not
negotiable and it is why a session row exists for a crossword even before a check
happens.

**The typed letters are written to `localStorage` on every keystroke** — no
network, instant resume, no debounce to tune. That is the fast path and it is
what a returning player hits essentially every time.

**The same letters are flushed to the server on leaving** — tab hidden, component
unmounted, and piggybacked on every check, which is a server round-trip anyway.
Not on a timer: a handful of writes per puzzle instead of one every few seconds,
which at 200 players is the difference between a trickle and a load-test finding.

On open, the two are reconciled by timestamp — the state blob carries its own
`saved_at`, so this is a comparison and not a schema addition — and the newer
wins, server taking ties.

That last part is the reason not to go client-only. The failure it fixes is
mundane and will happen during a five-day event: someone starts the crossword on
their laptop at lunch and picks it up on their phone on the train. Client-only
means their typing is gone and there is no way to tell them why. The cost of
avoiding it is one merge rule and two flush calls.

The fallback, if the merge proves fiddly in practice: keep letters in
`localStorage` only and let a device switch lose typing but never progress —
because checks used and status are server-side either way, the worst case is
retyping letters, not losing the puzzle. Worth knowing the floor is safe; the
hybrid is still what this spec builds.

*Player view:* grid geometry, derived numbering, clues, entry lengths, the
letters the player has typed, per-cell wrong marks from the last check, and
checks remaining. Never the answers, until terminal.

## 5. API

```
GET  /api/challenges/{id}/puzzle        → kind, player-safe view, session status
POST /api/challenges/{id}/puzzle/move   → a kind-discriminated move
POST /api/challenges/{id}/puzzle/save   → crossword only; stores letters, evaluates nothing
```

`save` is a flush, not an autosave — called on leaving the puzzle, not on a
timer. §4.3 has the reasoning.

One move endpoint rather than one per game, because every move needs the same
gate in the same order before its kind matters at all:

1. Resolve the challenge through the **player** visibility rules — a hidden,
   draft or unreleased puzzle is a 404 whatever id is supplied.
2. Rate limit (§8).
3. Refuse if locked, or if its unlock requirements are unmet — logged, as
   `submit_answer` already logs a probe at a locked challenge.
4. Refuse if the session is terminal.
5. Then, and only then, hand to the kind's engine.

`GET` creates no session. The session is created by the first move, so opening a
puzzle to look at it does not commit you to playing it.

### The normal submit path refuses puzzles

`POST /challenges/{id}/submit` on a puzzle challenge returns 409
`puzzle_challenge` — *"This one is played, not answered."* Otherwise the whole
design is decorative: the Wordle answer would be a `ChallengeAnswer` and anyone
could type it straight into the box.

A challenge therefore may not have both a puzzle and answer rules. The editor
refuses the combination in both directions.

## 6. Solving, and failing

**Completion is the solve.** The move that finishes the puzzle awards it through
the same code path a correct flag takes: a `Submission` row, XP valued at that
moment minus hints used, a `Solve` row inside a savepoint so a race resolves the
way it already does, and `progress.announce_changes` so levels, abilities,
achievements and any zone that just opened all fire.

That means extracting the award half of `submit_answer`
([challenges.py:282](../backend/app/services/challenges.py#L282)) into a shared
internal function that both paths call. **Not** reimplementing it — a second
copy of XP banking is how two scoring systems end up disagreeing at 2am on day
two.

Every move logs a `Submission`, right or wrong, with a compact canonical
rendering of the move as `submitted_value` (the guess; the four tiles; the grid),
capped at `MAX_SUBMISSION_LENGTH`. `is_correct` is true **only** on the move that
completes the puzzle — a correct Connections group is progress, not a solve, and
marking it correct would make the attempt log lie.

### Failure is terminal

Out of guesses, out of mistakes, or out of checks: `status = failed`, and that is
the day. No XP, no retry, no second session. The challenge stays on the board
marked as failed rather than reverting to unplayed, because "you had a go at this
and lost" is a different thing from "you have not started", and the board should
not pretend otherwise.

On a terminal session the answer is revealed — the word, the four groups, the
filled grid — under `reveal_on_fail`, which defaults on and can be turned off per
puzzle. A player who failed can see what it was; this is what makes losing
bearable and it is what the games do everywhere else.

It also means the answer is in circulation from the first failure onward. So is
it from the first solve. This is inherent to a shared daily puzzle and is not
something the platform can design away — the mitigation is that these are the
low-value challenges in a welcoming zone, not that we pretend nobody talks.

## 7. Authoring

**In the admin editor only.** The CSV gains no `puzzle` column: a challenge row
imported by CSV can be given a puzzle afterwards in the editor, and a puzzle is
authored content of a kind the CSV's flat shape does not express well.

The challenge editor gains a **Puzzle** section — kind, or None — which when set
swaps in a kind-specific form:

- **Wordle:** the answer, length, guess count, extra accepted words. On save, how
  many list words share the answer's length.
- **Connections:** four named groups of four tiles, levels 1–4, with duplicate
  and count errors called out per field rather than as one refusal.
- **Crossword:** a grid where cells are toggled to blocks, numbering drawn live
  as the geometry changes, and a clue and answer per numbered entry. Crossing
  conflicts are shown on the cells that conflict.

All three validate server-side; the client-side version is a convenience that the
server never trusts. Admins see the answers in full, as they already do for
answer rules ([admin_challenges.py](../backend/app/schemas/admin_challenges.py)) —
an admin who cannot see the answer cannot debug a puzzle nobody is solving.

Setting a puzzle hides `max_attempts` and defaults scoring to static; both are
meaningless or actively wrong for a puzzle.

Admin **preview** renders the puzzle read-only with its answers shown. It does
not create a session — an admin playing a puzzle they authored would put a
staff-owned session and submissions into the event's data for no benefit.

## 8. What this touches elsewhere

**Rate limiting.** The existing per-challenge limiter — 10 attempts per minute
([rate_limit.py:22](../backend/app/services/rate_limit.py#L22)) — is reused
unchanged and applies to moves. Every game's *entire* move budget is under ten
(six guesses, eight group attempts, three checks), so the limiter cannot
interfere with legitimate play while still stopping a script. The crossword
`save` endpoint is limited separately and logs nothing.

**Anti-cheat (spec 007).** Puzzle challenges join `exempt_challenges`, the set
the ladder challenges already use
([signals.py:112](../backend/app/services/signals.py#L112)) — a one-line change
to the query. Two hundred players guessing `AUDIT` on day one is not collusion,
and `shared_wrong_answers` and `first_try_solvers` would both be unreadable
otherwise.

**Event reset (spec 043).** A new group, **Puzzle play** → `puzzle_session`.
`challenge_puzzle` is authored content and is never reset, exactly as `loot_item`
is not. Note that resetting **Solves** alone leaves a failed session failed, so a
re-run of the event wants both groups.

**The AI assistant.** Puzzle config is not in any assistant context and must not
be added to one. It is not in `body`, so this holds by construction rather than
by discipline — but it is written down here because "the assistant is never given
answer-revealing content" is a standing rule and this is new content to not give
it. A player asking the System AI for a five-letter word about packet capture is
asking it a general-knowledge question, which is fine and is not a leak.

**The board.** The challenge list query gains a left join carrying `puzzle_kind`
and, for this player, `puzzle_status`, so a card can be badged as a game and
marked solved, failed or unplayed. The zone's cleared count is untouched — a
failed puzzle is simply not cleared.

**Achievements (spec 029).** Flat XP for a solve means skill is recognised here
instead. Triggers are predicates over stored history, so each of these is a
predicate over `puzzle_session` and nothing needs a new hook:

| Code | Earned by |
| --- | --- |
| `puzzle_first` | Finishing any daily puzzle. |
| `wordle_sharp` | A Wordle in three guesses or fewer. |
| `connections_flawless` | A Connections with no mistakes. |
| `crossword_clean` | A crossword solved on the first check. |
| `game_show_regular` | A puzzle of each of the three kinds. |
| `game_show_sweep` | Every puzzle in the zone solved, none failed. |

Names, System AI lines and loot tiers follow 029's format and are settled with
the roster, not here.

## 9. Non-goals

- **A fourth game.** The engine registry makes adding one cheap; this spec ships
  three.
- **Any content.** The fifteen-odd actual puzzles are authored in the editor, not
  written into this spec or a migration.
- **Shareable result grids.** The emoji-square share is the best-known thing
  about Wordle and it is also the fastest possible spoiler vector inside a
  competition. Not in this spec.
- **A leaderboard per puzzle**, or a streak counter. The scoreboard is the
  scoreboard.
- **Timers.** Nothing here is timed. A daily puzzle in a multi-day event is
  played between other things.
- **Replay after failure**, and replay after solving.
- **Preventing answer sharing.** §6 — accepted, not solved.
- **Puzzles in the CSV.**

## 10. Testing

*Model and authoring*

- A challenge may hold a puzzle or answer rules, never both, refused either way round.
- Each kind's config validator refuses: a Wordle answer of the wrong length; Connections with a duplicate tile, a fifth group, a group of three, or a repeated level; a crossword whose crossings disagree, whose entry runs off the grid, or which leaves a non-block cell uncovered.
- Crossword numbering is derived from geometry and survives a block being toggled.
- Deleting a challenge deletes its puzzle and every session; a solved puzzle challenge still cannot be deleted.

*Leakage — the point of the whole design*

- No player-facing response, for any kind, in any state, contains the answer while the session is `in_progress` — asserted against the serialised payload, not the schema.
- The answer appears only once the session is terminal, and only when `reveal_on_fail` allows.
- A locked, unreleased, hidden or draft puzzle returns 404 on both `GET` and `move`.
- A move against a challenge whose unlock requirements are unmet is refused and logged.

*Play*

- Wordle marks duplicate letters correctly (guessing `LEVEL` against `ELDER`).
- A guess outside the list is rejected, consumes no guess, and logs no submission; the answer itself is always accepted.
- Connections returns one away for three-of-four and costs a mistake; a repeated identical selection costs nothing; solving three groups auto-solves the fourth.
- A crossword check marks wrong cells without correcting them, and the save endpoint stores letters without consuming a check.
- Wordle and Connections sessions survive a reload: state comes back from the server, not the browser.
- A crossword resumes from `localStorage` when it is newer, from the server when it is newer, and from the server on a tie.
- Clearing `localStorage` mid-crossword loses typing and **not** checks used, wrong marks or status — the three checks do not come back.

*Scoring and failure*

- Completion banks XP once, through the same path as a flag, minus hints used, and announces progress.
- Two concurrent completing moves produce one solve.
- Running out is terminal: no XP, no new session, further moves refused.
- `POST /submit` on a puzzle challenge is a 409 and creates no solve.
- Every move logs a submission; `is_correct` is true only on the completing move.

*Elsewhere*

- Puzzle challenges are exempt from the shared-wrong-answer and first-try signals.
- The reset's Puzzle play group empties `puzzle_session` and leaves `challenge_puzzle` intact.
- The list marks a puzzle challenge as a game and carries this player's status.
- Only admins may read or write a puzzle's config; a player hitting the admin route is refused.

## 11. Decisions taken (2026-09-14)

1. **One challenge per puzzle per day** — not a rotating challenge. §2.
2. **Flat XP on completion**; skill is recognised through achievements. §8.
3. **Hard fail** — running out ends the day, with the answer revealed. §6.
4. **Completion is the solve**, awarded server-side; there is no flag to paste
   and the submit endpoint refuses puzzle challenges. §5, §6.
5. **The challenge detail page is the only surface.** Not the zone panel, not a
   dedicated game-show route. §1.
6. **Authored in the admin editor only**; no CSV column. §7.
7. **Wordle validates guesses against a shipped word list**, plus per-puzzle
   extra words, plus the answer itself. §4.1.
8. **The crossword checks the whole grid and marks wrong cells**, with a tight
   check limit. §4.3.
9. **Connections plays by the standard rules** — four mistakes, *one away*
   feedback, free shuffle and deselect, auto-solve of the last group, no cost for
   resubmitting the same four tiles. §4.2.
10. **Five days, fifteen puzzles, 1,950 XP**, on the schedule in §2. All three
    of a day's puzzles share a difficulty and a value.
11. **Crossword letters are `localStorage`-first, flushed to the server on
    leaving and on every check**, reconciled by timestamp on open. Checks used,
    wrong marks and status are server-side throughout. §4.3.

## 12. Open questions

None outstanding. Everything §11 does not cover is a content decision — the
fifteen puzzles themselves, and the achievement names and System AI lines, which
follow spec 029's roster format rather than this spec.
