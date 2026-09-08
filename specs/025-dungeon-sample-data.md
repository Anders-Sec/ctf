# Spec 025 — Dungeon Sample Data

Status: **approved** (2026-09-08)
Phase: 2/3 boundary
Depends on: 018 (abilities, skills, XP), 019 (the 22 zones and the progression
graph), 024 (the class roster)

A second sample-data generator that fills the **real** dungeon — the 22 seeded
categories and the 74 seeded skills — rather than inventing four zones of its
own. The existing generator stays; this adds a mode beside it.

## Why a second one rather than a change to the first

The existing generator builds a self-contained four-zone event with its own
categories (`Warm-Up (sample)`, `Web (sample)`…). That is the right shape for
testing the platform in isolation, and it purges cleanly because it owns
everything it made.

It is the wrong shape for looking at the *actual* dungeon. Right now 21 of 22
real zones have nothing published, so the map is dark, every percentage gate
past Intro is unsatisfiable, no ability or skill accumulates XP, and none of the
48 classes can ever unlock. Nothing downstream of a solve can be seen working.

So: a **dungeon mode** that places sample challenges into the real categories
with the real skills attached, leaving both untouched otherwise.

## A bug 024 introduced, fixed here

The existing generator creates three sample classes — `Rogue`, `Seer`, `Wizard` —
and its purge runs `DELETE FROM character_class WHERE name IN (...)`.

024 seeded a real `Rogue` and a real `Wizard`. So today:

- **Purging sample data deletes two real roster classes**, and the FK's
  `ON DELETE SET NULL` quietly returns every player who chose them to Classless.
- **Generating** then recreates them as bare sample classes — no rarity, no
  preference targets, no requirements — silently degrading two roster entries.

The generator no longer invents classes at all. The real roster exists now, so
sample players simply pick from it, and the purge stops touching
`character_class` entirely. That the sample data ever owned class rows was only
ever a stand-in for the roster not existing yet.

## What dungeon mode makes

- **No categories and no skills.** It reads the real ones and fails clearly if
  the roster migrations have not run.
- **Challenges spread across all 22 zones**, three or four each, with a
  difficulty mix per zone that rises with the zone's depth in the progression
  graph — so the early wings are approachable and the deep ones are not.
- **Real skills attached**, chosen from the skills whose `category_id` matches
  the challenge's zone, plus an occasional cross-zone skill so the overlap rule
  is visible. Enough coverage that skill levels actually move.
- **Hints** on a scattering of challenges, so the deferred-hint economy has
  something to show.
- **Players and parties** at a spread of progress: a few who have barely
  started, several mid-way, and one or two deep enough to have opened later
  wings and unlocked a tiered class. This is the part that makes the map, the
  gates and the class roster all visibly work.
- **Solves** consistent with that progress, respecting the real gates — a player
  never holds a solve in a zone they could not have opened.

Everything it creates is tagged with the existing `SAMPLE_PREFIX` slug and the
sample email domain, so the existing purge takes it all back out and the real
categories, skills and classes are never touched.

## API

The generator gains a mode rather than a second endpoint:

- `POST /api/admin/sample-data` — unchanged default (the standalone four-zone
  event), so nothing that exists today changes behaviour.
- `POST /api/admin/sample-data?mode=dungeon` — the new one.
- `DELETE /api/admin/sample-data` — unchanged; one purge covers both, since both
  tag their rows the same way.

Both remain refused in production.

## The admin UI

The existing sample-data control gains a second button — "Fill the dungeon" —
next to the current one, with a line saying what it does differently. Both share
the existing summary display and the single purge.

## Edge cases

- **Running dungeon mode twice** purges first, exactly as today, so it replaces
  rather than doubles.
- **A zone with no matching skills** still gets challenges; it just attaches
  whatever the zone's ability suggests instead. No zone is skipped.
- **The percentage gates.** Sample solves are generated *after* the challenges
  exist, so a player's progress is computed against the same gate evaluator the
  live game uses rather than a guess.
- **Real content already in a zone** is left alone and counts toward that zone's
  totals; sample challenges are added alongside it.

## Testing

- Dungeon mode creates no categories, no skills and no classes.
- It publishes challenges into real categories, covering every zone.
- Attached skills are real seeded ones.
- Purge removes every sample challenge and leaves all 22 categories, all 74
  skills and all 48 classes present.
- Purge no longer deletes any class, and a player's chosen class survives it.
- Both modes are refused in production.

## Non-goals

- Replacing the real challenge authoring — this is demo content, tagged as such.
- Realistic challenge bodies or working flags beyond the existing placeholder
  shape.
- Tuning the XP economy against the generated data; that wants real content.

## Decision

**Demo scale: three or four challenges per zone.** The goal is seeing every area
in use, not load. A load-shaped dataset is the 012 harness's job.
