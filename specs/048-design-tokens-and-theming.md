# Spec 048 — Design Tokens & Theming

Status: **draft**
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
| `border` | Default hairline | `stone` |
| `border-strong` | Emphasised divider, input outline | — |
| `content` | Primary text | `ink` |
| `content-muted` | Secondary text, labels | `muted` |
| `content-faint` | Placeholder, disabled | — |
| `accent` | Brand, links, primary action | `torch` |
| `accent-content` | Text/icon on top of `accent` | — |
| `danger` | Destructive action, broken challenge, failure | `torch` (shared) |
| `warning` | Needs attention, not yet failing | `torch` (shared) |
| `success` | Solved, healthy, delivered | ad hoc greens |
| `info` | Neutral notice | — |
| `focus-ring` | Keyboard focus outline | `#ffca7a` literal |

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

**Open question — see §9.1.** The recommendation here is that admin surfaces get
*light and dark only*, not the flavour presets: an admin working at 11pm wants a
dark screen, but the admin area is a tool and should not be restyleable into
something unfamiliar. Player-facing surfaces get all four.

That is a small difference in implementation — the admin shell stamps a
restricted theme set — but it needs deciding before the picker is built, because
it decides whether the picker is one control or two.

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

## 9. Open questions

1. **Does the admin area get themes?** (§6.) The instruction was that theming is
   player-facing. Recommend: admin gets light/dark only, players get all four — a
   dark admin screen is a practical need at 11pm, but the admin area should not be
   restyleable. Needs confirming before the picker is built.
2. **Does High Contrast belong in the same picker as the flavour themes?** It is
   an accessibility setting, not a taste. Recommend keeping it in one list — a
   separate "accessibility" menu is a place people do not look.
3. **What happens to the illustrated map under a dark theme?** The 22 zone tiles
   (spec 020) are raster art with baked-in lighting, and the map already carries
   its own dark atmosphere from spec 023. Recommend the map stays
   **theme-invariant** — it is already dark, it is the one surface with real art,
   and re-rendering 22 tiles per theme is not a Phase 3 budget. Worth confirming
   rather than assuming.
