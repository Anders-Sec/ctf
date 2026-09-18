# Spec 072 — Tests for the Party Page

Status: **done**
Phase: 3 (Polish & Operability) — quality of life
Depends on: 005 (the union rule), 067 (the party page's standing and coverage)
Second of two: 071 focus, **072** this.

`routes/PartyPage.tsx` is **577 lines across eight components** and has no tests.
It is the only route of that size in the app without any.

## 1. Why this one

It is not the largest file in the app, but it is the one where a silent failure
costs the most. Everything on it is a **write**, and most of the writes are hard
to take back during a live event:

- Forming a party, joining one, asking to join one.
- Accepting and declining requests at the door.
- **Removing** a member, **handing over** leadership, **leaving**.
- Renaming the party and changing who can get in.

Spec 067 added the standing panel and coverage to this page and shipped them on
the strength of a manual check. §5 of that spec claimed *"every existing party
test passes untouched"*, which was true only because **there are none** — an
error already recorded in 067 §8. This closes it.

## 2. What gets tested

Eight components, by what a player actually does:

**Browsing** (`PartyBrowser`, `PartyList`, `PartyRow`)
- The empty state when no parties exist.
- The **four mutually exclusive row states**: full, password-protected, private
  without a password (ask to join), and open (join directly). This branch is a
  four-deep ternary with a `null` fallthrough and is exactly where an unhandled
  combination would hide.
- The password form appears on demand and submits the typed password.
- "Ask to join" goes to `Request sent` and stays disabled after success.
- A failed join renders the server's error rather than silently doing nothing.

**Forming** (`CreatePartyForm`)
- Submit stays disabled under three characters.
- The password field appears only for a private party.
- A public party sends `join_password: null` — not the typed-then-hidden value.

**Your own party** (`MyParty`)
- Leader sees Make leader / Remove on others and on **neither themselves nor**
  the other leader; a member sees no roster buttons at all.
- Join requests are fetched **only** for a leader (`enabled: isLeader`).
- The standing panel and `PartyCoverage` render, and the panel's absence is not
  an error — `panel.data &&` means a slow board leaves the page usable.

**The door** (`JoinRequestsSection`)
- The count in the heading matches the list.
- Accept and decline call with the request's id, not the user's.

**Settings** (`PartySettings`)
- Unchanged fields are sent as `undefined`, not as their current value — the
  patch semantics the form relies on.
- A blank password is not sent.

## 3. What the reading turned up

**Two dead paths, both the same shape**, verified end to end rather than
inferred — and one claim of mine that was simply wrong.

**1. The join-request message.** `PartyRow` calls `requestToJoin(team.id)` with
no second argument. The API client accepts an optional `message`, the backend
stores it and returns it, and `JoinRequestsSection` renders
`“{request.message}”` when present — so a leader has a quote block that can
never contain anything. Someone asking to join a private party cannot say who
they are, and the leader approves a bare name.

**2. `clear_password`.** Implemented the whole way down — `TeamUpdate` schema,
route, and `update_team`, which sets `join_password_hash = None` — and typed in
the frontend client. **No UI has ever sent it.** A leader who sets a password
cannot remove it while staying private; the only escape is to go public and
back.

Both are the shape of the dead Affinity dropdown from spec 058: a complete path
with one missing end, whose test passes because it asserts the call and not the
effect.

**And one thing I asserted that is false.** An earlier draft of §4 said
switching a party to public leaves its password stored, so switching back to
private silently restores it. It does not. `update_team` clears
`join_password_hash` on the switch to public, with a comment giving that exact
reason. The claim was made from the frontend’s `join_password: undefined` alone,
without reading the service it calls.

## 4. Decision needed: pin, or fix?

**The tests are written against current behaviour**, except where they would be
pinning something plainly broken. The dead message path is the only such case
found, and the recommendation is to **fix it**: a textarea on "Ask to join",
capped, optional, passed through. It is perhaps fifteen lines and it makes an
existing feature work rather than adding one.

Everything else stays exactly as it is, including things that are arguably
rough:

- **No confirmation on Remove, Leave or Make leader.** All three are one click
  and all three are hard to undo. Recorded here rather than changed, because
  adding friction is a design decision and the memory note *"admin tools are
  setup tools"* does not obviously extend to a player removing a teammate
  mid-event. Flagged for the user.
- **Removing a password while staying private** now has a control, because the
  plumbing was already there and unused (§3.2). Same judgement as the message
  path: wiring up an existing capability is smaller than writing a paragraph
  explaining why it is missing.

## 5. Shape

One file, `routes/PartyPage.test.tsx` — colocated, which is what this codebase
actually does; the `__tests__/` directory in the first draft exists nowhere in
it. Following the existing pattern:
`renderWithProviders`, a mocked `api/teams` module, a `useSession` stub for the
three states that matter (no party, member, leader). Roughly 25–30 tests.

No backend tests: the endpoints have them, and this is about the page.

## 6. Decisions

1. **Fix the dead paths, or pin them?** Fixed — both of them (§3, §4).
2. **Do Remove and Leave want a confirmation?** **Neither was built.** The
   recommendation stands — Remove yes, Leave no, because removing acts on
   somebody else while leaving is a decision the person has already made — but
   it is a design change rather than a test, and 072 was scoped to pin
   behaviour. Still open, and still one line of work when you want it.

## 7. What the build changed

- **32 tests, not the 25–30 estimated**, in `routes/PartyPage.test.tsx`.
  Colocated, which is what this codebase does; the `__tests__/` directory in
  §5's first draft exists nowhere in it.
- **§4 asserted a bug that does not exist** — see §3. That is the second claim
  in this spec made from one end of a path without reading the other, after
  §5's "every existing party test passes untouched". Both were caught by
  reading the code the claim was about.
- **Three tests were wrong before the code was**, each from a wrong belief
  rather than a typo: that `ErrorMessage` echoes the server's prose (it renders
  our own copy keyed on `error.code`, deliberately); that passing `undefined`
  omits a value (a destructuring default swallows it, so the "usable without a
  standing" test was quietly given the standing back and proved nothing); and
  that a `<section>` without an accessible name is a `region`.
- **Frontend suite: 668 tests, up from 636.**
