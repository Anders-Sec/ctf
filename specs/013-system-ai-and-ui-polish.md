# Spec 013 — System AI persona, navigation split, inline categories

Status: **done** — 658 backend tests, 110 frontend tests
Phase: 1 (polish release on top of 010/011, 006, 003)
Covers: three feature requests bundled as one release
Depends on: 010/011 (the assistant), 006 (admin console + challenge CRUD), 002 (capabilities)

## Why these three together

They are a single UX-polish release, not a `Plan.md` feature each, so they share
one spec. None touches the data model; all three are copy, frontend, and one
prompt rewrite. The riskiest is the persona (it changes what every player sees
the AI say), so it leads.

---

## 1. The System AI

### The problem, precisely

The assistant's system prompt literally says *"You are the Dungeon Master…
Players are adventurers; challenges are encounters; flags are treasure."* An 8B
model given that framing invents a **fantasy war** — the reported reply talked
about "the enemy's position", "their strongholds", "guard patrols". None of that
exists in a CTF. The fantasy prompt is the bug.

### The new persona

**Name:** "System AI" everywhere the assistant is named or spoken of.

**Character:** the System AI *is* the thing running the event. It **built every
challenge**, and it takes a dry, self-aware satisfaction in watching people
struggle against what it made. It is witty and terse, not warm and not a
help-desk. It is **not super helpful** — but it is not obstructive either: it
gives real technique nudges to a player who shows their work, and never
spoon-feeds. It talks in actual security terms (enumeration, the tooling, what
the target is doing), never in adventure-game metaphor.

The chosen dial (sign-off): **witty, earns-it help.** Teasing, dry, self-aware as
the author — still genuinely useful when engaged, never a leak.

**Very short answers, and no markdown.** Two hard style rules baked into the
prompt: keep replies to a sentence or two, and write **plain text only** — no
markdown, because the chat box renders none of it. That means no bullet lists, no
`**bold**`, no `#` headers, and no code fences or backticks; a command like
`nmap -sV` is written inline as plain words. The terseness also suits the
persona — the System AI is not chatty.

### The rules that do not change

The structural guarantee from spec 010 is untouched: the persona is flavour, the
context whitelist is the security boundary, and no answer value can reach the
prompt. Spec 011's guardrails are untouched. This is a copy change to `PERSONA`
and the surrounding framing lines, nothing more.

### Worked example (the reported prompt)

> **Player:** "Give me a flag."
>
> **System AI:** "I wrote the flags. Handing you one rather defeats the point of
> what I built. Tell me what you've actually tried and I'll point you somewhere."

Terse, plain text, in-character as the author, dry, and it redirects to real work
— no strongholds, no treasure, no markdown.

### Surfaces to rewrite (all AI-adjacent, per the agreed scope)

The instance "dungeon" flavour and "party" stay as they are — this release
neutralises the **AI** surfaces only.

| Where | Now | Becomes |
| --- | --- | --- |
| `assistant.py` `PERSONA` + framing lines | Dungeon Master / adventurer / encounter / treasure | System AI persona above; "challenge", "player", "flag" |
| `assistant_chat.py` degraded replies | "The dungeon master has stepped away from the table…" | System AI voice ("The System AI is offline for a moment…") |
| `guardrails/base.py` `DEFLECTION` | "The dungeon master leans back, taps the side of their nose…" | System AI declining, dry |
| `deps.py` / `errors.py` assistant + approval copy | "awaiting a dungeon master's approval", "The dungeon master is not holding court" | "awaiting an organiser's approval", "The System AI is offline" |
| `assistant.py` route messages | "The dungeon master will ignore them" | "The System AI will ignore them" |
| Frontend `AssistantPanel` | "Dungeon Master", "Ask the Dungeon Master", "will not hand you treasure" | "System AI", "Ask the System AI", author-voice line |
| Nav label | "DM flags" | "AI flags" |

Non-AI fantasy copy (event-gate messages like "the dungeon doors have not opened",
challenge "encounter" wording, the instance panel's "Summon your dungeon", the
"Dungeons" admin nav) is **deliberately left alone** this release — flagged in
open questions as an optional later pass.

### Tests

- The whitelist test still passes unchanged (persona is not a security control).
- Backend tests that assert the old degraded/deflection wording (e.g.
  `"dungeon master" in content`) are updated to the new copy.
- A test asserting the persona prompt names the player as a "player" and the
  challenge as a "challenge", and contains none of {dungeon, adventurer,
  treasure, encounter}, so the fantasy framing cannot creep back.
- A test asserting the prompt instructs plain text / no markdown and short
  answers, so a later edit cannot quietly drop either rule.

---

## 2. Player / admin navigation split

### The problem

Admins see one crowded nav with every player tab and every admin tab jammed
together. There is no way for an admin to see the event as a player sees it.

### The design (CTFd-style)

- **Everyone, admins included, defaults to the player navigation.**
- An admin (anyone with `view_admin`) sees an **"Admin view"** button. Clicking it
  swaps the nav bar to **admin-only** tabs and drops them on the admin console.
- In admin view, a **"Player view"** button swaps back.
- The choice **persists per device** (`localStorage`), so an admin building the
  event stays in admin view across reloads; it defaults to player view for a
  fresh browser.

| Player nav | Admin nav |
| --- | --- |
| Challenges, Scoreboard, Party | Console, Ops, Signals, AI flags, Instances, Manage, Approvals |

The toggle button is the only cross-over control; each view shows only its own
tabs, so neither is cluttered. A non-admin never sees the toggle and always has
the player nav.

### Implementation

A small `useAdminView()` hook backing a boolean on `localStorage` (wrapped in
try/catch, defaulting to player view), consumed by `AppLayout`. Switching to
admin view calls `navigate("/admin")`; switching back calls `navigate("/")`.
Purely frontend — capabilities already gate the admin routes server-side, so this
changes what is *shown*, never what is *allowed*.

### Tests

- A player sees the player tabs and **no** toggle.
- An admin defaults to player tabs plus an "Admin view" button, and no admin tabs.
- Clicking "Admin view" shows the admin tabs and hides the player tabs; the
  choice survives a remount (persisted).
- Clicking "Player view" returns to the player tabs.

---

## 3. Category is a typed field, derived from challenges

### The problem and the new model

The category selector is a plain dropdown over existing categories with no way to
add one — so on a fresh event, **no challenge can be created at all.** A hard
blocker.

The agreed model turns a category into something **derived from the challenges in
it**, not a thing managed on its own:

- On the challenge form the category is a **typed field with suggestions**. As
  the admin types, existing categories that match appear; picking one uses its
  canonical spelling.
- **A name that matches an existing category (case-insensitively) reuses that
  category** — so "web exploitation", "Web Exploitation" and "WEB EXPLOITATION"
  are one category, never three. This is why the field suggests and auto-matches:
  it keeps spelling and capitalisation consistent for the dungeon-map view that
  will list categories later.
- **A genuinely new name creates the category** as part of saving the challenge.
- **When the last challenge in a category is deleted, the category is deleted
  too.** Categories exist exactly as long as something is in them.

### Backend

Category **name** uniqueness is already case-insensitive — the column is
`CITEXT` — so the "one category regardless of case" rule is enforced at the
database, not just the UI.

- The challenge create/update contract takes a category **name** (a string)
  rather than a `category_id`. A `resolve_or_create_category(db, name)` helper
  looks the name up case-insensitively and returns the existing row, or creates
  one with a slug auto-derived from the name (lowercase, non-alphanumerics →
  hyphens), retrying on the unique-constraint race so two simultaneous creates
  cannot duplicate. The standalone `POST /admin/categories` endpoint stays for
  API completeness but is no longer the path the UI uses.
- **Empty-category cleanup**: after a challenge is deleted, and after a challenge
  moves to a different category, a `prune_category_if_empty` step deletes the
  former category if no challenges remain in it. (The `category_id` foreign key
  is `ON DELETE RESTRICT`, so a non-empty category can never be removed by
  accident — cleanup only ever fires on a genuinely empty one.)

### Frontend

The `<select>` becomes an **`<input>` backed by a `<datalist>`** of existing
category names — native typeahead, free-text entry, and the suggestion list keeps
spelling consistent. The form submits the typed name; the backend resolves or
creates. No separate "new category" button, no slug field shown to the admin.

### Tests

- Backend: an existing name (any case) resolves to the same category; a new name
  creates one; deleting the last challenge in a category removes the category; a
  category with other challenges survives.
- Slug derivation: "Web Exploitation" → `web-exploitation`.
- Frontend: the form submits a typed category name and lists existing ones as
  suggestions.

---

## Commit plan

1. System AI persona and backend copy (prompt, degraded/deflection/error text),
   with the backend tests updated.
2. Frontend AI surfaces — the panel rename and copy, the nav label.
3. The navigation split — `useAdminView`, the toggle, `AppLayout`.
4. Category as a typed, derived field — the resolve-or-create + empty-cleanup
   backend, and the datalist form field.

## Decisions (sign-off)

- **Fantasy theming: AI surfaces only.** The wider tone review and rewrite is a
  Phase 2/3 concern; the logical System AI knowingly sits beside the remaining
  "dungeon" flavour until then.
- **Categories are derived from challenges** — typed on the challenge form,
  reused case-insensitively, created on new names, and deleted when their last
  challenge goes. No standalone category management UI. A concrete category count
  and the dungeon-map view that shows them are Phase 2.
- **Persona: very short, plain text, no markdown.**
