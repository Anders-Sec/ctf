# Spec 058 — Content Admin Consistency

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability) — the first quality-of-life item
Depends on: 041/042 (the Challenges page this copies), 049 (the Content group)
Resolves: spec 048 §11.4 — how a secret theme is unlocked

The four Content pages were built at different times for different sizes of
data, and it shows. Challenges got a rebuild at 242 rows (spec 041); Skills and
Classes are still the flat lists they were at eight. This gives all four the
same shape, and gives Achievements the editing they never had.

## 1. What each page is today

| | Challenges | Skills | Classes | Achievements |
| --- | --- | --- | --- | --- |
| Rows | 242 | ~45 | 48 | 110 |
| New item | Full form | Name only | Name only | Form, most fields |
| Search | ✅ server-side | ✗ | ✗ | client-side |
| Filters | ✅ 6 + problem filters | ✗ | ✗ | one ("needs copy") |
| Grouping | ✅ by zone, collapsible | ✗ flat | ✗ flat | ✗ flat |
| Detail | ✅ side drawer | ✗ | ✗ | inline expander |
| Bulk | ✅ 6 operations | ✗ | ✗ | ✗ |
| Fields editable | every one | **name only** | **name, order, description** | **5 of 9** |

The two that stand out:

- **Skills can only be created by name and deleted.** `description`, `kind`
  (useful vs funny) and `category_id` are all in the model, all in
  `UpdateSkillRequest`, and reachable from no UI at all. Creating a funny skill
  is impossible from the page that exists to manage them.
- **Achievements cannot have their reward edited.** `loot_box_type`,
  `loot_rarity` and `no_loot_line` are on the model and absent from
  `UpdateAchievementRequest`, so what an achievement *pays out* is set by the
  seed and unchangeable afterwards. That is the gap this spec is most needed
  for, because §5 hangs theme unlocks off it.

Classes are a third case: the page edits name, order and description, and the
model's `rarity`, `preferences` and `requirements` — which are the whole of spec
024's recommender — are not editable anywhere.

## 2. One shape, four pages

Challenges is the template, and its shape is extracted rather than copied:

```
┌──────────────────────────────────────────────┬─────────────┐
│ Skills                          [+ New skill]│  Injection  │
│ Search…      [Type▾][Zone▾][Problems▾]       │  Artistry ✕ │
│                                              │             │
│ ▼ Web Attacks            6 skills · 2 funny  │ Name        │
│   ☐ Injection Artistry      useful   12 ch.  │ [        ]  │
│   ☐ Auth Bypass             useful    8 ch.  │ Kind        │
│   ☐ Reflexive Inspect…      funny     0 ch.  │ (useful ▾)  │
│ ▶ Crypto                 4 skills · 1 funny  │ Zone        │
│ ▶ (no zone)              3 skills            │ ▸ Advanced  │
└──────────────────────────────────────────────┴─────────────┘
```

Five shared pieces, extracted into `components/content/`:

| Piece | What it does |
| --- | --- |
| `ContentPage` | Header with the title, the description line and the **New** button; the filter bar; the list; the drawer slot. |
| `ContentFilterBar` | Search box plus a set of `<select>` filters the page declares. |
| `ContentGroupList` | Collapsible groups with a summary line per group; collapsed state per admin in `localStorage`. |
| `ContentDrawer` | The right-hand editor. Does not move the list; warns on close with unsaved changes; delete lives in its header. |
| `ContentBulkBar` | Appears when rows are selected; the operations are declared per page. |

**The drawer, not an inline expander**, for the reason spec 041 gave: the list
does not move, so working through a list does not mean re-finding your place
after every edit — and it is what makes a selection column usable at all.

**The list row is short on purpose.** Everything a row needs to be *found* and
*scanned* by, and nothing else; the full record is one click away in the drawer.
That is what lets 242 rows and 110 rows use the same page without either
becoming a scroll.

## 3. Per page

Grouping, filters and the row are the only things that differ.

### Challenges (unchanged)

Already this shape. It contributes the components and gains nothing except
whatever falls out of the extraction. Its tests must pass untouched — if they
do not, the extraction changed behaviour and that is a bug, not a refactor.

### Skills

- **Group by** zone (`category_id`), with a `(no zone)` group last. A skill with
  no zone is not an error — the model's `SET NULL` is deliberate — but it is
  worth seeing together.
- **Group summary**: `6 skills · 2 funny · 14 challenges`.
- **Filters**: Kind (useful / funny), Zone, and problem filters —
  *No description*, *No zone*, *Attached to nothing* (a skill no challenge
  feeds is XP that lands nowhere, the skills equivalent of 041's "no skills").
- **Row**: name · kind · challenges-using-it · description present.
- **Drawer**: name, kind, zone, description, display order.
- **Bulk**: set kind, set zone, delete.

### Classes

- **Group by** rarity — it is the axis the roster is authored along, and
  `common` through `mythic` is a natural split of 48. (Five groups, not six:
  the `Rarity` enum is common/uncommon/rare/legendary/mythic.)
- **Group summary**: `12 classes · 3 with no requirements`.
- **Filters**: Rarity, Has requirements, Has preferences, *Needs copy* (the
  description is still null or placeholder).
- **Row**: name · rarity · preference count · requirement count · players
  wearing it.
- **Drawer**: name, rarity, description, display order, **preferences** and
  **requirements** — both editable, which is new. A preference is an ability or
  a skill (the XOR the model enforces); a requirement is a skill and a level.
- **Bulk**: set rarity, delete.

### Achievements

- **Group by** loot box type, with a `(no loot)` group. That is the axis an
  admin actually works along when balancing rewards, and it puts the ones that
  pay nothing together where `no_loot_line` matters.
- **Group summary**: `14 achievements · 3 need copy · 2 inert`.
- **Filters**: Loot box, Rarity, Secret, and problem filters — *Needs copy*
  (spec 030's placeholder check, kept), *No trigger* (inert, will never fire),
  *No reward and no line* (pays nothing and says nothing about it).
- **Row**: name · code · trigger status · reward · held-by count.
- **Drawer**: name, description, earned-by, display order, secret, **loot box
  type, loot rarity, no-loot line** — the three that were unreachable — and the
  reward section from §5. Code stays uneditable for spec 030's reason: it joins
  to a trigger *and* to every award already granted.
- **Bulk**: set loot box, set rarity, set secret, delete.

Delete keeps spec 030's rule: **refused once anyone holds it.** Taking an
achievement back from someone who earned it is worse than living with a badly
named one.

## 4. Backend gaps

Mostly small, and all of them are fields that already exist on models:

- **`UpdateAchievementRequest`** gains `loot_box_type`, `loot_rarity`,
  `no_loot_line`, and the reward fields from §5. `CreateAchievementRequest`
  likewise.
- **`UpdateClassRequest`** gains `rarity`, and class preferences and
  requirements get endpoints — `PUT /admin/classes/{id}/preferences` and
  `PUT /admin/classes/{id}/requirements`, replacing the whole set in one call
  the way `PUT /admin/challenges/{id}/skills` already does.
- **List endpoints gain the counts the rows need** — challenges-per-skill,
  players-per-class, preference and requirement counts — as aggregate
  subqueries, never an N+1 across 110 rows.
- **Bulk endpoints** for skills, classes and achievements, following
  `challenge_bulk`'s shape: a list of ids, one action, per-item results so a
  partial failure is reported rather than hidden.

Every write stays `Admin` and audited; reads stay `Staff`, matching what those
routers already do.

## 5. Achievement rewards, and the secret themes

**Decided (2026-09-17): secret themes are unlocked by achievements.** This is
spec 048 §11.4's answer, and it is why the reward fields have to become
editable.

An achievement's reward becomes two independent things, because they are:

| Field | Meaning |
| --- | --- |
| `loot_box_type` + `loot_rarity` | Unchanged. The box it drops, as spec 038 defines it. |
| **`unlocks_theme`** | New, nullable. A theme id from the roster. Earning the achievement grants that theme to the player. |

Both may be set, either may be null, and an achievement that grants neither
still needs `no_loot_line` — which is the existing rule, now stated once for
both kinds of reward.

**A new `user_theme_unlock` table**: `user_id`, `theme`, `unlocked_at`,
`source_achievement_id`. A row is written when the achievement is awarded, and
spec 048's `/settings` page lists the themes a player holds. The validation
rule from 048 §5 is unchanged and now load-bearing: a player may select a theme
they hold, and anything else falls back rather than erroring.

**The drawer's theme picker offers every secret theme**, with the two
already-visible ones excluded — granting somebody Parchment is not a reward.

One thing this deliberately does not do: **retroactive granting**. Spec 028's
rule is that an achievement created after the fact awards nothing for work
already done, and attaching a theme to an existing achievement follows the same
rule. Handing a theme to somebody who already earned something is §5.1's job —
a deliberate admin action, never a silent side effect of editing a row.

### 5.1 The manual grant

The user detail drawer (spec 052) gains a **theme toggle per secret theme**: on
means the player holds it, off means they do not.

Granting and revoking are both `Admin` and both audited, and a revoke that takes
away the theme a player is currently wearing falls them back to the event
default rather than leaving them on something they no longer hold.

**That fallback had to be built, not reused.** The draft of this spec claimed
spec 048 §5's existing behaviour covered it; it does not. That one falls back on
a theme id that is *no longer a theme*, and a revoked theme is still perfectly
real — so `resolve_theme` now takes what the player holds and declines to honour
a secret theme missing from it. Passing nothing still means "unknown", so the
callers that cannot cheaply look holdings up do not silently downgrade anybody.

Rows carry their source: `achievement` or `admin`. An admin grant for a theme
the player later earns legitimately is not a conflict — the row already exists
and the award is idempotent.

## 6. Colour and navigation aids

The brief asked for anything that makes a large list easier to work in. Held to
the standing rule that colour is never the only signal:

- **Group headers carry their summary**, so a collapsed group still tells you
  what is inside it — the thing that makes collapsing safe.
- **A problem count in the filter bar.** "3 need copy · 2 inert" as clickable
  text, which is spec 041's problem filters made visible rather than hidden in
  a dropdown.
- **Rarity and kind render as their existing tokens** — the six-step ladder for
  class rarity, which is already theme-invariant and already carries its name as
  text.
- **An inert or incomplete row is marked in the list**, not only in the drawer.
  Spec 030 made trigger status visible for exactly this reason; the same applies
  to a skill attached to nothing and a class with no requirements.
- **Sticky group headers** while scrolling a long group, so the zone or rarity
  you are inside stays visible.

No new colour tokens. Spec 048's roles cover all of this, and a fifth accent
would be a fifth thing to contrast-test.

## 7. Testing

- The extracted components render each page's declared filters, groups and
  bulk operations.
- **Every existing Challenges test passes untouched.** The extraction is a
  refactor; a changed assertion means changed behaviour.
- Each page: search and every filter narrow correctly and server-side where the
  endpoint supports it.
- Each page: the drawer opens without moving the list, warns on close with
  unsaved changes, and saves every field the model has.
- **Skills**: kind and zone are settable from the UI, which they were not.
- **Classes**: rarity, preferences and requirements are settable; the
  preference XOR (ability *or* skill, never both) is enforced server-side with
  its own test.
- **Achievements**: loot box, rarity, no-loot line and `unlocks_theme` are all
  settable; delete is still refused once held; code is still uneditable.
- **Themes**: awarding an achievement with `unlocks_theme` writes an unlock row;
  the player can then select that theme and not before; a theme removed from the
  roster still falls back rather than erroring.
- Bulk operations report per-item results, and a partial failure is visible.
- Every list endpoint issues a constant number of queries at 110 and 242 rows.

## 8. What this spec does not do

- **Reordering by drag.** `display_order` is editable as a number, as it is
  today. Drag ordering is its own interaction and none of these lists is
  ordered by hand often enough to earn it.
- **A CSV import/export for skills, classes or achievements.** Challenges has
  one because 242 rows were authored offline (spec 040). These are authored in
  place.
- **Touching the Map page.** It is in the Content group but it is a spatial
  editor, not a list, and this shape does not fit it.

## 9. Open questions

Signed off 2026-09-17. All three decided as below.

1. ~~**Rarity or preference target for Classes?**~~ **Rarity**, as recommended.
   Preference target stays a filter.
2. ~~**Its own notification for a theme unlock?**~~ **No.** It is an achievement
   notification and nothing more — two messages would make one achievement feel
   like two events.
3. ~~**A direct admin grant?**~~ **Yes, in the Users page.** A per-theme toggle
   in the user detail drawer (spec 052), so a theme can be handed to one player
   without inventing an achievement for them. See §5.1.

## 10. Deviations, as built

### Challenges keeps its own table

§2 said the five shared pieces would be *extracted* from Challenges, which
implies Challenges then uses them. It does not. `ContentPage`,
`ContentFilterBar`, `ContentGroupList`, `ContentDrawer` and `ContentBulkBar` are
modelled on it and used by the other three pages; `ChallengeTable` is untouched.

The reason is that its rows and headers are not the generic ones. A challenge row
edits difficulty, XP and state **in place**, and a zone header carries that
zone's XP budget against a target (`ZONE_XP_BUDGET`, `ZONE_EXPECTED_ROWS`) plus
its boss status. Generalising those would have meant rewriting 410 lines of
working, well-tested code so that it could arrive at the shape it already has,
and §3's own constraint — *its tests must pass untouched* — is the constraint a
rewrite is least likely to hold.

The outcome §2 wanted is four pages that look and work alike, and that is met.
What is not met is one implementation behind all four, so a change to the shared
shape has to be made twice. That is the cost, and it is recorded here rather than
discovered later.

*Verified: no Challenges test was modified, and all of them pass.*

### Two small additions

- **`useSelection`**, a hook beside the components. The awkward part of a
  selection is identical on all three pages — a filter that hides a selected row
  must not widen what a bulk action does — so it is written once.
- **`Field`, `SelectBox`, `RowFlag`, `inputClass`**, exported alongside. Not in
  §2's table, but without them each drawer lays its fields out slightly
  differently, which is the thing this spec exists to stop.

### Found while building

Two bugs, neither the subject of this spec:

- **The Classes page's Affinity dropdown did nothing.** It sent
  `affinity_skill_id`, a field `UpdateClassRequest` does not have; pydantic
  ignores unknown keys, so every selection returned 200 and changed nothing.
  Spec 024 replaced affinity with preferences and the control was never removed.
  Its test asserted the *request body* rather than any effect, so it passed
  throughout. Preferences editing replaces it.
- **`Skill.challenge_count` was missing from the frontend type**, so the count
  the list endpoint had been computing since this spec's backend pass was
  discarded on arrival.
