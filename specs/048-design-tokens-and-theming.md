# Spec 048 — Design Tokens & Theming

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: nothing — this is the foundation the rest of Phase 3 builds on
Blocks: every other Phase 3 spec that renders anything

Players and the admin can pick a theme. That is the feature. Most of the work is
not the picker — it is that **the app cannot currently be themed at all**, and
every component built before that is fixed is a component that gets built twice.

## 1. Why this is first, and what is actually broken

`tailwind.config.js` maps Tailwind colour names onto CSS custom properties, with
a comment saying the Phase 3 art pass can retheme the app by swapping values in
`index.css` "without touching a single component." That design is right. It has
not been followed:

- **~100 uses of raw `bg-white/xx` across 41 component files.** `white` is a
  stock Tailwind colour, not a token. Every card, nav bar and panel in the app is
  a translucent white rectangle that no token can move. On a dark theme they stay
  white.
- **23 hardcoded hex/rgba literals in `.tsx`**, plus more in `index.css` — the
  zone hover glows at `rgba(255, 157, 61, 0.9)` and `rgba(63, 214, 208, 0.35)`,
  and the focus outline at `#ffca7a`.
- **`torch` is doing two unrelated jobs.** It is the brand accent *and* the alert
  colour: `text-torch` marks "likely broken" on the dashboard, and
  `border-torch/50 bg-torch/10` is the urgent alert box. Any theme that picks a
  warm accent makes alerts indistinguishable from ordinary emphasis; any theme
  that picks a calm accent makes alerts invisible. These have to become separate
  tokens before either can be themed.
- **No dark-mode story at all.** No `prefers-color-scheme` handling, no
  `data-theme` attribute, no root class. The token names are also *pigments*
  (`parchment`, `ink`, `stone`) rather than roles, so a dark theme would have to
  set `--color-parchment` to something that is not parchment.

So the deliverable is: a role-named semantic token layer, a migration of the
existing offenders onto it, and only then a picker.

## 2. The token set

Pigment names stay as aliases so the migration can be incremental, but **new code
uses roles only**. Roles, and what each is for:

| Token | Role | Today |
| --- | --- | --- |
| `surface` | Page background | `parchment` |
| `surface-raised` | Cards, panels, nav — anything sitting on the page | `bg-white/60` |
| `surface-sunken` | Wells, table header bands, inset areas | — |
| `surface-overlay` | Drawers, modals, the assistant panel | ad hoc |
| `border` | Decorative hairline — row dividers, card edges | `stone` |
| `border-strong` | **Control boundary** — input outline, toggle | — |
| `content` | Primary text | `ink` |
| `content-muted` | Secondary text, labels | `muted` |
| `content-faint` | Placeholder, disabled | — |
| `accent` | Brand fill — a button, a badge | `torch` |
| `accent-strong` | The accent **as text**: links, emphasis | — |
| `accent-content` | Text/icon on top of `accent` | — |
| `danger` | Destructive action, broken challenge, failure | `torch` (shared) |
| `warning` | Needs attention, not yet failing | `torch` (shared) |
| `success` | Solved, healthy, delivered | ad hoc greens |
| `info` | Neutral notice | — |
| `focus-ring` | Keyboard focus outline | `#ffca7a` literal |

Two further tokens are theme-invariant, alongside the ladder below:
`on-fill` (text on any saturated fill — a puzzle tile, a generated avatar) and
the `puzzle-*` set (spec 044's board colours). Green/amber/grey on a Wordle tile
is a convention players arrive already knowing, and a theme that reassigned it
would be lying to them.

The six-step ladder (`loot-*` / `boss-*` / `rarity-*`) stays exactly as it is. It
is already tokenised, already shared between bosses and loot, and it is semantic
rarity rather than theme decoration — it should look broadly the same in every
theme, and spec 024's rule that colour is never the only signal keeps it safe
where it does shift.

**Elevation is a token, not an opacity.** `bg-white/60` encodes "lighter than the
page", which is only true on a light theme. `surface-raised` is an opaque colour
per theme, so a dark theme raises by getting lighter and a light theme by getting
whiter, and no component has to know which it is in.

## 3. How a theme is applied

`data-theme="<name>"` on `<html>`. Each theme is a block in `index.css`
redefining the role tokens; the default block sits on bare `:root`, so an
unstamped document is still fully painted.

```css
:root { --surface: 245 241 232; /* … */ }          /* parchment, the default */
:root[data-theme="dark-dungeon"] { --surface: 18 17 20; /* … */ }
```

**No flash of the wrong theme.** A small inline script in `index.html` stamps the
attribute from `localStorage` before the bundle parses. React later reconciles it
against the server-held preference, which is the real source of truth.

## 4. The presets

Curated presets, **not a colour picker**. A picker cannot be contrast-tested, and
a player who chooses unreadable colours then files a bug against the platform.

| Preset | For |
| --- | --- |
| **Parchment** | Today's look. The default, and the event default unless changed. |
| **Dark Dungeon** | The one people will actually ask for. Warm accent held, surfaces dropped to near-black. |
| **Torchlight** | Higher-contrast dark with a stronger amber accent — the "I am in a bright room" dark. |
| **High Contrast** | Accessibility preset. Maximum separation, heavy borders, no translucency. Not a stylistic choice; it exists so the platform is usable by someone who needs it. |

Adding a fifth later is a CSS block and a roster entry. The roster lives in one
place shared by the backend (which validates a stored preference) and the
frontend (which renders the picker) — a theme that exists in one and not the
other is the failure mode to design out.

## 5. Where the preference lives

`user.theme` — a nullable string column. Null means "use the event default."

Stored server-side rather than in `localStorage` alone, because it should follow
a player from their laptop to their phone mid-event, and because the admin needs
an event-wide default that has to live on the server anyway. `localStorage` keeps
a copy purely to kill the flash in §3.

- `GET /api/me` gains `theme` (the effective one) and `theme_source`
  (`"user"` | `"event"`), so the picker can say "following the event default"
  rather than pretending the player chose it.
- `PATCH /api/me/theme` — `{ "theme": "dark-dungeon" | null }`. Null clears back
  to the default.
- `event_config.default_theme`, set on the Theme settings page (spec 049 files it
  under Settings). Changing it moves every player who has not chosen.

An unknown theme name — a preset removed after someone selected it — falls back
to the default rather than erroring. A stored preference must never be able to
break a login.

## 6. Does this apply to the admin area?

**Yes, in full.** Decided at sign-off: the admin area gets the same colour
presets as the player area. What stays out of the admin area is *word* theming —
dungeon flavour in labels, headings and copy — which is the standing Phase 3
naming decision in `CLAUDE.md` and is spec 049's business, not this one's.

That split is the useful one. Colour is a working condition: an admin at 11pm
wants a dark screen for the same reason a player does, and building a second
restricted picker to deny them the other two presets would be effort spent making
the tool worse. Vocabulary is different — "Live Instances" is faster to act on
than "Dungeons" when something is broken.

So: **one picker, one preset roster, applied everywhere.** The admin shell stamps
`data-theme` exactly as the player shell does.

## 7. The migration

The unglamorous majority of the work, and the part that must not be skipped.

1. **Add the role tokens** alongside the existing pigment tokens. Nothing breaks;
   nothing looks different.
2. **Split `torch`.** Introduce `danger` and `warning`, and move every alert-ish
   use off `accent`. This is a visible change in the making — today they are the
   same colour, and after this they are allowed to differ.
3. **Migrate `bg-white/xx` → `surface-raised`** across the 41 files. Mechanical,
   and it is the change that makes a dark theme possible at all.
4. **Migrate the literals** in `.tsx` and `index.css`, including the map glows and
   the focus outline.
5. **Add a lint rule** — a CI check that fails on `bg-white`, `text-black`, a hex
   literal, or `rgb(`/`rgba(` in `src/**/*.tsx` outside the token definitions.
   Without it this regresses within a week, which is exactly how it got here.

Step 5 is what makes steps 1–4 stay done.

## 8. Testing

- Every preset defines every role token — a test enumerates the roles from the
  shared roster and asserts no theme is missing one.
- **Automated contrast check**: `content` on `surface`, `content-muted` on
  `surface`, `content` on `surface-raised`, `accent-content` on `accent`, and each
  of `danger`/`warning`/`success` on both surfaces, all meeting WCAG AA (4.5:1
  body, 3:1 large text and UI borders), in every preset. This test is what
  justifies presets over a picker, so it is not optional.
- The lint rule from §7.5 fails on a raw colour, with a test that it does.
- A user with no preference gets the event default; changing the event default
  moves them; a user with a preference is unmoved by that change.
- An unrecognised stored theme name falls back to the default rather than 500ing
  `/api/me`.
- The inline stamp applies the stored theme before first paint.
- `prefers-reduced-motion` behaviour from spec 023 is unchanged by any preset.

## 9. What implementation changed

Recorded per `CLAUDE.md`: the spec was signed off before building, and these
are the places reality pushed back.

1. **`accent` split into `accent` and `accent-strong`.** One value cannot do
   both jobs. The brand torch at `194 106 42` gives **3.46:1** as text on
   parchment — failing AA body text — while white on it gives **3.78:1**, also
   failing. Nudging it darker fixes the text case and breaks the fill case, and
   lighter does the reverse. Fills and text therefore have separate values.
2. **`border-strong` is specifically a control boundary, and `border` is exempt
   from 3:1.** WCAG 1.4.11 covers boundaries a user must be able to *find* — an
   input outline, a focus ring — not decorative rules. Holding a row divider to
   3:1 would draw a heavy black line between every table row in every theme, so
   the two weights are tested against different thresholds.
3. **`on-fill` and the `puzzle-*` set added**, theme-invariant (see §2).
4. **The map's glow colours became `--map-glow-warm` / `--map-glow-cold`**,
   defined once rather than themed. This resolves open question 3 below: the map
   stays theme-invariant.
5. **A latent bug fixed on the way through.** `bg-stone-500` emitted **no CSS at
   all** — the config replaces Tailwind's stone scale with a single token, so
   the class matched nothing. The Wordle "not in the word" tile and a puzzle
   badge have had no background since spec 044. Both now use `puzzle-absent`.

## 10. Amendment — the toggle, and the secret themes

Requested after reviewing the built presets (2026-09-17). This replaces §4's
four-preset picker and part of §5.

**Torchlight is dropped.** It was meant to be the high-contrast dark, and next
to Dark Dungeon it read as the same theme. Two values apart is not a preset.

**The everyday control becomes a light/dark toggle, not a picker.** Two themes
carry it — Parchment and Dark Dungeon — and a toggle is the right shape for a
two-way choice: one click, no menu, no reading. A picker earns its place when
there is something to choose between, and there no longer is.

**High Contrast becomes its own switch**, on a new player settings page, not an
entry in the theme list. It is an accessibility need rather than a taste, and
mixing it into a list of looks asks people to browse for it. It **overrides**
the light/dark choice while it is on, and turning it off returns the player to
whichever side of the toggle they were on — so it is a second axis, not a third
theme, and that is why it needs its own stored field.

### 10.1 Secret themes

Three themes that exist but are not offered in the toggle. How a player comes to
have one is deliberately undecided — see §11.4 — so for now they are selectable
by the admin (for the event default and for their own account) and by nobody
else.

| Theme | What it is |
| --- | --- |
| **Purple Squirrel** | The team's in-joke. Dark mode in purple, with squirrels across the background. A gag, and **exempt from the contrast rules** — that exemption is declared in the roster and asserted by the test, so it is a recorded decision rather than a theme that quietly fails. |
| **DND** | Rustic and dungeon-like. Tavern candlelight rather than the parchment page. |
| **The Mr. Anderson** | Green on black. Matrix terminal. |

DND and Mr. Anderson are held to AA like every non-exempt theme. Green on black
clears it comfortably; it is the gag theme that needed the exemption.

### 10.2 What this changes in the model

`user.theme` keeps holding a theme id, and gains a companion:

- **`user.high_contrast`** — boolean. While true, High Contrast is served
  whatever `theme` says. Storing it separately is what lets the switch be
  reversible without the platform having to remember a "previous theme".
- Resolution becomes: `high_contrast ? "high-contrast" : (user.theme ?? event.default_theme ?? "parchment")`.

`event_config.default_theme` is unchanged, and the admin may set it to any theme
including a secret one — an event themed as Mr. Anderson for a day is a thing
someone will want.

### 10.3 Surfaces

- **The top bar** carries the light/dark toggle. It replaces the picker.
- **A player settings page** (`/settings`) carries appearance, the High Contrast
  switch, and — once §11.4 is decided — any secret theme the player holds.
- **The admin theme page** lists every theme, secret ones included and marked as
  such, for both the event default and the admin's own account.

## 11. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. ~~**Does the admin area get themes?**~~ **Decision (2026-09-17): yes, all four
   presets, one picker, everywhere.** Colour theming applies to the admin area;
   *word* theming does not — admin labels and copy stay practical per the standing
   naming decision. See §6.
2. **Does High Contrast belong in the same picker as the flavour themes?** It is
   an accessibility setting, not a taste. Recommend keeping it in one list — a
   separate "accessibility" menu is a place people do not look.
4. ~~**How is a secret theme unlocked?**~~ **Decision (2026-09-17): by
   achievement.** An achievement gains an `unlocks_theme` field, and earning it
   grants the theme. The roster, the award records and the notification were all
   already built, so this is a lookup rather than a new mechanism. Specified in
   **spec 058 §5**, which also makes the reward fields editable — they had been
   on the model and reachable from no UI.
5. **Should High Contrast have a dark variant?** It is currently one
   light-based palette, and a player who needs maximum contrast *and* a dark
   screen is not served. Recommend leaving it as one until someone asks: two
   high-contrast palettes is two more things to keep passing the contrast test,
   for a combination nobody has yet requested.
3. ~~**What happens to the illustrated map under a dark theme?**~~ **Resolved
   during implementation: the map is theme-invariant.** Its glow colours are
   defined once (§9.4) and `DungeonMap.tsx` is allow-listed in the colour linter
   with that reason recorded in the allowlist itself. The 22 tiles are raster art
   with baked-in lighting and the map already carries its own dark atmosphere
   from spec 023.
