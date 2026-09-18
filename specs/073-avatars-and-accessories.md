# Spec 073 — Avatars: Sigils, Accessories and the Editor

Status: **done**
Phase: 3 (Polish & Operability) — feature
Depends on: 016/024 (classes), 029 (achievements), 038 (loot), 052 (the avatar endpoint)
First of two: **073** the parts that need no GPU, 074 the generation service.

`Avatar.tsx` says *"Phase 3 replaces this with real art."* This is that, minus
the model — everything here renders on the API box with Pillow and works whether
or not the AI host is switched on.

## 1. The line this spec draws

**Compositing, not generation.** Everything in 073 is deterministic: the same
inputs produce the same PNG, every time, in milliseconds, with no GPU.

That is a deliberate architectural split rather than a convenience. Accessories
are **rewards**, and a reward has to be recognisable — if a wizard hat were
generated fresh each time it would look different on every player and stop
reading as a badge. It also means the reward system does not go dark when the
AI host does; spec 074 becomes optional infrastructure rather than a dependency.

## 2. Data model

`user.avatar_blob` and `avatar_updated_at` **stay exactly as they are** — they
are the rendered result, and `GET /users/{id}/avatar` already serves them with
an ETag. Nothing about the serving path changes.

What is new is the recipe that produced them:

```
user.avatar_source   enum: sigil | entra | generated        (default sigil)
user.avatar_config   JSONB: { layers: [ {accessory, x, y, scale, rotation} ] }
```

Plus one authored table, following the class roster's pattern (DB-backed,
seeded from a module in the repo):

```
AvatarAccessory
  slug, name, slot, image_key, rarity
  anchor_x, anchor_y, anchor_scale, anchor_rotation   -- sensible defaults
  unlock_kind: always | class | achievement | loot_rarity
  unlock_ref:  the class slug, achievement slug, or rarity
```

**Unlocks are derived, never granted.** You have the wizard hat because your
class is wizard, or because you hold the achievement — computed on read from
data that already exists, the way achievements work. No grant table means no
grant table to fall out of sync.

`slot` (head, eyes, shoulders, frame) exists so two hats cannot occupy one head.
One accessory per slot.

## 3. One renderer

Every avatar becomes a PNG through a single Pillow path: base image, then each
layer composited at its transform, then cached into `avatar_blob`. Re-rendered
when `avatar_config` changes, when the class changes, or when the base changes.

The base is one of three things, and the renderer does not care which:

- **A sigil** — procedural, deterministic from the user id (§4).
- **The Entra photo** — already cached in `avatar_blob` today.
- **A generated portrait** — spec 074, absent for now.

The win is that `Avatar.tsx` collapses to an `<img>`. The colour-and-initial
fallback, the `hasAvatar` branch and `initialsColor` all go: **everyone has an
avatar**, so there is no second rendering path to keep consistent.

## 4. Sigils

The current default is a coloured circle with one letter. The replacement is a
**procedural heraldic crest** derived from the user id — shield shape, division,
charge, and a two-colour scheme, all indexed off the same hash.

Three reasons it earns its place over the letter: it is themed on day one with
no GPU and no setup; it is the fallback whenever generation is unavailable or
declined; and a crest is distinguishable at 40px in a roster in a way that
twenty people whose names begin with S are not.

Colours come from the theme-invariant ladders (spec 048) so a crest looks
deliberate in both themes.

## 5. The editor

Accessories carry authored anchors that are right for most people, so the editor
is **correction, not composition**: drag to position, two sliders for scale and
rotation, per layer. Nothing else.

It stores **the transform, not a flattened image**. That matters more than it
sounds: unlocking a new hat next Tuesday must not lose the fit of the glasses,
and the avatar has to re-render at 40px and 200px from the same recipe.

Live preview is client-side canvas, because dragging against an HTTP round-trip
is not dragging. The server render on save is authoritative — the preview only
has to be close enough to aim with. **This is two renderers and it is a real
cost**; the mitigation is that the server's output is what is ever stored or
shown, and a test pins one known config against an expected composite.

## 6. API

```
GET   /avatar/accessories        what exists, and which you have unlocked
GET   /avatar/me                 your current source + config
PUT   /avatar/me                 set source and layers
POST  /avatar/me/reset           back to the sigil
GET   /users/{id}/avatar         unchanged
```

`PUT` validates that every accessory is one you have actually unlocked, server
side, against the derived set — the client's idea of what it owns is not
evidence. Locked accessories are **withheld from the payload's usable set**
rather than hidden in the UI, per the standing rule from 018 and 028.

## 7. Where accessories show up

Everywhere `Avatar` already renders: the scoreboard, the party page and roster,
the character sheet, the inbox, the assistant. That breadth is the whole payoff
— a class overlay makes the party page look like a party, and it makes a class
choice visible to other people, which it currently is not.

This does not collide with the XP rule (059 §2, 064 §7.1). Accessories reveal
that you *did* something, the way boss stars already do on the board. They never
reveal a figure.

## 8. Admin

One surface, practical name, following 030 and 058: list accessories, upload the
art, set slots, anchors, rarity and unlock rule, enable or disable. Plus the
moderation backstop 074 will need anyway — **reset this player's avatar** —
which is one button and is much easier to add now than mid-event.

## 9. Testing

- The renderer is deterministic: same config, same bytes.
- Every slot holds at most one accessory.
- Unlock derivation: class-locked, achievement-locked, loot-locked and `always`,
  each from a user who does and does not qualify.
- `PUT` rejects an accessory the user has not unlocked.
- A sigil is stable for a given user id and differs across ids.
- Changing class re-renders; **an earned accessory is not revoked** (§11.3).
- Accessories survive a re-render at a different size.

## 10. What this does not do

- **No generation.** Spec 074.
- **No work-photo transformation.** Dropped: plain img2img at the strength
  needed to add a hat also restructures the face, and a mangled portrait of a
  colleague is not a thing you can un-see at a work event. Overlaying the real
  Entra photo — which §3 supports — is the safe half of that idea and keeps the
  face untouched.
- **No animation, no frames beyond the `frame` slot.**

## 11. Decisions

1. **Heraldic crest.** Shield, division, charge and two colours, all indexed off
   a SHA-256 of the user id — 4 divisions x 8 charges x 12 tinctures x 4 metals,
   which is ample for 200 players and legible at 40px.
2. **Visible immediately**, no publish step.
3. **An accessory survives a class change** — earned is earned.

## 12. What the build changed

- **`avatar_blob` needed splitting in two.** The spec said it stays as the
  rendered result, which is right, but it was also holding the Entra photo the
  render *starts from*. Keeping both in one column meant either re-compositing
  a 2048px canvas on every one of 200 roster rows, or losing the original the
  moment a hat went on. `avatar_base` holds the source; `avatar_blob` is the
  cache, dropped by `invalidate()` when the recipe changes.
- **SHA-256, not `hash()`.** Python salts `hash()` per process, so a crest
  would have differed on every API pod — a player refreshing would watch their
  own sigil change.
- **Three errors in the authored roster, all caught by tests that now guard
  them:**
  - it invented a **Paladin** class, which is not one of the 48;
  - it invented a **`boss_first_kill`** achievement, which is not one of the 94;
  - it used **`mythic`** as a loot rarity, which is the top of the *class*
    ladder — the loot ladder ends at `celestial`. Two ladders, two
    vocabularies, confused in one list.
  Each would have been an accessory nobody could ever earn, with nothing to say
  so. `test_roster` now checks every `unlock_ref` against the real class roster,
  the registered achievement triggers, and the loot rarities.
- **The crescent charge was drawn wrong** — it punched a transparent hole
  through the shield instead of biting a curve out of a disc, so the page showed
  through. Charges are composited on their own layer now.
- **Seeded at boot, not by migration.** The class roster seeds by migration
  (0027), but migrations in this repo never import from `app` — they are frozen
  snapshots — so a migration would have meant a second copy of the roster in
  SQL. A best-effort startup seed keeps it in one place.
- **`Avatar` lost `hasAvatar` entirely**, from six call sites, along with
  `initialsColor` and the whole fallback branch.
- **Counts:** 28 accessories authored, 48 avatar tests, backend 1630 passing,
  frontend 680.
