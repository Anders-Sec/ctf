# Spec 067 — The Party Page

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 005 (the union rule this exists to serve), 059 (the party panel),
060 (the sheet it mirrors), 062 (board ordering)
First of four: **067** the party, 068 the ending, 069 the ticker, 070 settings.

The last nav item the Phase 3 passes did not reach, and the one with the
clearest gap.

## 1. Two problems

### It knows less about your party than a stranger's screen does

Since spec 059, `GET /scoreboard/teams/{id}` returns a party's rank, level,
distinct solve count, achievement count, deduplicated boss stars, founding date,
and a roster with every member's class and level. That is what a player sees
when they click somebody else's party name on the scoreboard.

`TeamDetail` — what your **own** party page reads — returns names, membership
and a created date.

### Nothing helps a party play as a party

Spec 005's rule is that **a party scores each challenge once**, however many
members solve it: *"size buys speed and coverage, never a higher ceiling."*

The consequence is that two members working the same challenge is wasted effort,
and **nothing on the platform says so.** At eight members over five days that is
the most expensive silence in the product.

## 2. The party sheet

The same shape as the character sheet (060), because a party is a character of
sorts and the two should read as one family:

```
┌─ The Mimics ───────────────── Rank 4 of 21 ─┐
│  ●●● ●● ●    6 bosses · 38 solved · 12 awards│
├─ Coverage ──────────┬─ Roster ──────────────┤
│ Networking  8/10    │ Grix   Rogue   Lv 7   │
│ Web Attacks 3/12 ←  │ Rin    Analyst Lv 5   │
│ Crypto      0/9  ←  │ Vek    —       Lv 3   │
│ Forensics   6/8     │                       │
│ 🔒 The Vaults       │ Join requests (1)     │
└─────────────────────┴───────────────────────┘
```

**The header is `/scoreboard/teams/{id}`**, which already returns every figure in
it. The page currently makes a different call for less.

### 2.1 Coverage

Per zone: how many of its challenges **the party** has claimed, out of how many
it can see. Zones with gaps are marked; a sealed zone shows as sealed.

This is the feature. It answers "where should we go next" with a party's own
numbers rather than a player's, and it makes the union rule visible: the bar
moves when *anybody* clears something, which is exactly what the scoring says.

**It needs a new endpoint.** `/challenges` reports `solved` for the *caller* —
`challenge.id in solved_ids` where the ids are that one player's. A party's
coverage is the union across current members, which only the server can compute.

### 2.2 Who has claimed what

Opening a zone lists its challenges with the member who cleared each one, and
nothing beside the rest.

That is the coordination fix, stated as plainly as it can be: *Rin has this one;
it will not pay twice.* It is not a lock and it is not a claim system — spec 005
already decided the scoring, and this only shows what the scoring already does.

### 2.3 The rest

Roster, join requests, party settings, leave, kick, promote and the party
browser are **unchanged in behaviour**. They are the working half of this page.
They move into the new layout and keep their tests.

## 3. Coverage is your own party only

`GET /teams/{id}/progress` is refused unless the caller is a **current member**.

Another party's coverage is not a view, it is reconnaissance: it would say which
zones a rival has not touched and exactly which challenges are unclaimed. The
scoreboard's party panel is the public view of a party and it stays as it is.

That is a different rule from everything else in Phase 3, which has been about
redacting content rather than gating a whole endpoint. It is warranted here
because the payload is *strategy*, not flavour.

## 4. API

`GET /teams/{id}/progress` — members only.

```
{
  zones: [{ name, slug, cleared, total, sealed }],
  solved_by: { "<challenge_id>": "Rin" }
}
```

- `zones` counts the same *player-visible* challenges the board shows, so the
  denominators match what members actually see.
- `solved_by` names the **earliest** solver of each claimed challenge, which is
  the one the union rule credits (spec 005 keeps the earliest solve).
- A departed member's solves leave with them, exactly as they do for score and
  stars — the same roster the union is taken over.

One grouped query for the counts and one for the solvers. No model change and no
migration.

## 5. Testing

- Coverage counts distinct solves across current members, not the sum: two
  members who both cleared one challenge move the bar once.
- A member who leaves takes their unique solves out of coverage.
- Denominators match the board's visible set, sealed zones included as sealed.
- `solved_by` names the earliest solver, and is absent for unclaimed challenges.
- **A non-member gets a 404 from `/progress`** — the reconnaissance test.
- Staff get the same refusal: this is about membership, not rank.
- The header renders rank, stars, solves and awards from the panel endpoint.
- Every existing party test — browse, create, join, request, kick, promote,
  leave, settings — passes untouched, or changes for a reason named in its
  commit.

## 6. What this does not do

- **Change scoring.** Spec 005's union rule is the thing this makes visible, not
  something it alters.
- **Add claiming or locking.** Showing who has a challenge is a fact; reserving
  one is a mechanic, and a bad one at this scale.
- **Show another party's coverage.** §3.
- **Touch the party browser's rules.** Capacity, visibility and join passwords
  are spec 006's and are untouched.

## 7. Open questions

1. **Should coverage count challenges a member cannot see?** A zone sealed for
   one member and open for another has two honest denominators. Recommend
   **counting what the party can collectively see** — the union again, applied
   to visibility, since that is the set the party can actually work on.
2. **Should `solved_by` name anybody, or just say "claimed"?** Naming is more
   useful and mildly more exposing inside a party. Recommend **naming**: it is
   your own party, and "ask Rin how they did it" is the point.
