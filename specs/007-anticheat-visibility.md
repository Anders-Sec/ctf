# Spec 007 — Anti-Cheat Visibility

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Admin Tooling (anti-cheat visibility)
Depends on: 002 (party history), 003 (submission log), 005 (boards), 006 (console)

## Purpose

Surface activity that *might* be answer-sharing, so a human can look at it.

`Plan.md` is emphatic that this is "flagged for admin review, **not
auto-actioned** in Phase 1", and that constraint shapes everything here: nothing
in this spec changes a score, disables an account, or sends anybody a message.
It computes, it displays, and it stops.

Done when an organiser can open one screen, see which pairs of players look like
they shared an answer, read the evidence behind each one, dismiss the ones that
are innocent, and pull up a single player's full timeline when they want to look
properly.

## The framing this spec needs

**These are conversation starters, not evidence.** This is a work event: the
people on this screen are colleagues, and the most common cause of every signal
below is two people sitting next to each other talking about a puzzle, which is
the point of the event. A platform that presents statistical coincidence as
proof of misconduct would do real damage to real people.

So, deliberately:

- The console calls them **signals**, never "cheaters" or "violations".
- Every signal shows its own **innocent explanation** alongside the suspicious
  one.
- Nothing is auto-actioned, and the spec ships no mechanism that could be.
- Signals are visible to staff only, and never to players — not their own, and
  not anyone else's.

## Non-goals

- Auto-actioning of any kind. Disabling an account already exists (002) and
  stays a deliberate human decision with a written reason.
- Scoring penalties. A `score_adjustment` with a reason (006) is the tool, used
  by a person who decided to use it.
- Machine learning, or anything with a threshold nobody can explain to the
  person it accused.

## Signals

Computed on demand from data specs 002–004 already record. Nothing new is
collected — this spec adds no tracking, only reads what is already there.

### 1. Identical unusual wrong answers

Two players in **different parties** submitting the exact same wrong string.

Sharing an answer usually means sharing the *whole* answer, including a typo. A
rare string appearing in two unrelated players' attempts is the strongest signal
available and it is nearly free — `submission.submitted_value` is already indexed.

**Innocent explanation, shown alongside:** the string is an obvious guess for
that challenge, or the two are sitting together and one read theirs out.

Noise control: a value submitted by *many* players is a common guess, not
sharing, so a value is only interesting when **2–4** distinct players used it.
Trivial values (empty, "test", "flag", the challenge title) are excluded by a
minimum length and an obviousness filter.

### 2. A solve close behind another party's solve

Player B solves within a short window of player A, with **no prior wrong
attempts**, and they are in different parties.

First-try-immediately-after-someone-else is what a passed answer looks like.

**Innocent explanation:** the challenge was easy, or a wave had just unlocked
and everyone hit it at once. The signal reports how many people solved it in the
same window, so a general stampede is visible as a stampede.

### 3. First-try solves, repeatedly

A player whose solves are overwhelmingly correct on the first attempt, across
many challenges.

Strong players do this on easy challenges. Doing it on the hard ones, every
time, is different — so the signal weights by challenge difficulty and by what
everyone else's attempt count looked like on the same challenge.

**Innocent explanation:** they are simply good, or they worked it out offline
before submitting, which is normal play.

### 4. Late recruitment

A player joining a party close to the end of the event, bringing a large number
of solves with them.

Flagged in spec 005 as the price of portable scores and open rosters. Not
against the rules — it is a consequence of rules you chose — but worth seeing.

**Innocent explanation:** they were left partyless and someone took them in.

### 5. Submission cadence

Attempts arriving at near-constant intervals, which is what a script looks like
and what a person does not. Rate limiting already caps the rate (003); this
notices the *regularity*, not the volume.

**Innocent explanation:** a person methodically working a wordlist by hand, at
a steady pace.

### Deliberately weak: shared IP address

Two accounts submitting from the same address is a classic signal and **is
close to useless here.** Everyone at a work event sits behind the same corporate
NAT; the whole field will share an address.

It is computed, shown last, and **labelled as unreliable in this environment** —
because an organiser who does not know that will read it as damning. It can be
turned off entirely in config, and probably should be.

## Review workflow

Signals are computed on demand rather than stored: a stored flag goes stale the
moment the data behind it changes, and a table of historical accusations against
named colleagues is not a thing to keep.

The only thing persisted is a **dismissal** — one small table recording that a
staff member looked at a specific finding and concluded it was fine, so the
console stops showing it. Dismissals carry a note and are audit-logged.

`signal_dismissal`: `signal_type`, `subject_key` (a stable hash of the finding's
participants and challenge), `note`, `dismissed_by_user_id`, `created_at`.

## Player timeline

The screen an organiser actually needs when a signal looks real: one player's
complete activity in order — submissions with their values, solves, hint
unlocks, party joins and departures, and the audit entries about them.

Almost every signal resolves in seconds once the timeline is visible, usually
innocently, and this is the difference between a suspicion and an answer.

## API surface

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/admin/signals` | staff | All signal types with counts and findings |
| GET | `/api/admin/signals/{type}` | staff | One type, in full |
| POST | `/api/admin/signals/dismiss` | staff | `{signal_type, subject_key, note}` |
| GET | `/api/admin/players/{id}/timeline` | staff | Everything that player did, in order |

Staff-gated, not admin-gated: organisers are exactly the people who should be
reviewing this, and none of it changes anything.

## Thresholds

All configurable, with defaults chosen to be quiet rather than thorough — a
console crying wolf gets ignored by hour two:

| Setting | Default |
| ------- | ------- |
| Shared wrong answer: distinct players | 2–4 |
| Shared wrong answer: minimum length | 8 characters |
| Close-behind solve window | 120 seconds |
| First-try ratio to flag | 90% over ≥ 5 solves |
| Late recruitment: window before event end | 2 hours |
| Late recruitment: solves brought | ≥ 5 |
| Shared IP | disabled by default |

## Edge cases

- **A player with no activity.** Timeline renders empty, not an error.
- **A challenge everyone gets wrong the same way.** Excluded by the upper bound
  on distinct players — a popular wrong guess is not a conspiracy.
- **Two players in the same party sharing.** Not flagged. Working together is
  the point of a party; the signals are all cross-party.
- **A player who has left every party.** Compared on their party membership at
  the time of each submission (`team_id_at_submit`), not their current one.
- **A dismissed signal whose evidence grows.** The `subject_key` covers the
  participants and challenge, so a *new* finding between the same people on a
  different challenge appears fresh rather than staying dismissed.
- **The event has not started.** Every signal returns empty rather than
  dividing by zero on an empty dataset.
- **Staff accounts.** Excluded from every signal; they are not competing.

## Testing

- Each signal fires on a constructed case and stays silent on its innocent twin
  — the same shape of data with the participants in one party, or the value
  submitted by twenty people rather than two.
- Same-party collaboration never appears.
- Staff never appear.
- A dismissal hides exactly its own finding and nothing else.
- The timeline orders everything correctly and renders empty for a new player.
- Every endpoint refuses a player, and allows an organiser.
- Signals compute against an empty database without error.

## Commit plan

1. Signal computation service, all five plus the IP one
2. `signal_dismissal` migration, dismissal endpoint and filtering
3. Player timeline endpoint
4. Frontend: signals console and timeline

## Open questions

1. **Shared IP: ship it disabled, or leave it out entirely?** Proposed
   disabled-by-default. It is genuinely unreliable on a corporate network and I
   would rather it not be the first thing an organiser reaches for.
2. **Should players see anything?** Proposed no. The alternative — telling a
   player they have been flagged — turns a statistical coincidence into an
   accusation before a human has looked at it.
