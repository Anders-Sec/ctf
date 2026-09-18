# Spec 072 — Tests for the Party Page

Status: **draft**
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

One finding, verified end to end rather than inferred:

**The join-request message is a dead path.** `PartyRow` calls
`requestToJoin(team.id)` with no second argument. The API client accepts an
optional `message`, the backend stores it and returns it, and
`JoinRequestsSection` renders `“{request.message}”` when present — so a leader
has a quote block that can never contain anything. Someone asking to join a
private party cannot say who they are, and the leader approves a bare name.

This is the same shape as the dead Affinity dropdown found in spec 058: a
complete path with one missing end, whose test would have passed because it
asserted the call and not the effect.

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
- **Switching a party to public leaves its password stored.** `join_password`
  is only ever sent when non-blank, so there is no way to clear one. Switching
  back to private silently restores the old password. Left as is.

## 5. Shape

One file, `routes/__tests__/PartyPage.test.tsx`, following the existing pattern:
`renderWithProviders`, a mocked `api/teams` module, a `useSession` stub for the
three states that matter (no party, member, leader). Roughly 25–30 tests.

No backend tests: the endpoints have them, and this is about the page.

## 6. Open questions

1. **Fix the dead message path, or pin it?** Recommend fixing (§4).
2. **Do Remove and Leave want a confirmation?** Recommend **Remove yes, Leave
   no** — removing acts on somebody else, and leaving is a decision the person
   has already made. Not built unless you say so.
