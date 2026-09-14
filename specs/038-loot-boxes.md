# Spec 038 — Loot Boxes

Status: **draft** (2026-09-14) — awaiting sign-off
Phase: 2 (D&D Mechanics), with the visual treatment deferred to Phase 3
Depends on: 029 (the achievement roster), 031 (boss tiers), 028 (notifications)

Every achievement drops a box. The box has a **type** and a **rarity**, and that
pair chooses from an authored set list of **titles** — one of which a player can
wear next to their name on the scoreboard.

This spec covers the logic and the content. What a box *looks like* when it
opens is Phase 3's problem, and nothing here should constrain it.

## Why a title, and not an item that does something

The failure mode for loot is obvious: a funny item name with no consequence is
read once and never looked at again.

A title fixes that for almost no cost, because **the scoreboard is where people
actually look**. Wearing *Persistence Without Variation* next to your name is a
joke that keeps working, visible to everyone, every time the board is opened.

It stays cosmetic. No XP, no ranking, no gating — the line 015 and 016 both drew
holds: identity never touches the scoreboard's ordering, only its presentation.

## The ten box types

Derived from grouping the 117 achievements by what earning them says about the
player. Every achievement belongs to exactly one.

| Box | What earns it | Achievements |
| --- | --- | --- |
| Boss Box | the per-zone boss kills | 22 |
| Adventurer's Box | turning up, volume, levels, the difficulty ladder | 17 |
| Specialist's Box | skills, abilities, class identity | 14 |
| Brute Force Box | wrong answers, at volume and at length | 13 |
| Interrogator's Box | everything aimed at the System itself | 13 |
| Saboteur's Box | leaning on the machinery until it makes a noise | 11 |
| Cartographer's Box | wings entered, wings emptied | 9 |
| Pathfinder's Box | speed, and being first through a door | 7 |
| Party Box | other people | 6 |
| Purist's Box | refusing help, and refusing it to no effect | 5 |

DCC's funniest box names work by calling the player stupid, and `core.md`'s
BOUNDARIES block rules that out. *Brute Force Box* rather than *That Wasn't Too
Smart, Was It? Box* — the same joke, aimed at the method rather than the person.

## Rarity

The six tiers already in the platform, reusing the names from 031's boss ladder:
**bronze, silver, gold, platinum, legendary, celestial**.

- **Fixed per achievement**, set in seed data and editable by an admin. The
  alternative — deriving rarity from how many players hold the achievement —
  is self-balancing and genuinely attractive, but it moves during the event, so
  the same achievement would drop bronze on day one and platinum on day three.
  A set list cannot be authored against a moving target.
- **Boss Boxes take their rarity from the boss tier** set in 031. A Floor Boss
  drops a Celestial Boss Box, exactly as your tier notes already say. One fact,
  configured once.

### Not every type spans every tier

Sixty set lists is more content than this feature is worth. Most types only make
sense across two or three tiers — a Party Box is never celestial, a Purist's Box
does not start at bronze:

| Box | Tiers | Lists |
| --- | --- | --- |
| Boss Box | all six | 6 |
| Adventurer's Box | bronze → gold | 3 |
| Specialist's Box | silver → celestial | 5 |
| Cartographer's Box | silver → platinum | 3 |
| Interrogator's Box | bronze → gold | 3 |
| Brute Force Box | bronze → silver | 2 |
| Saboteur's Box | bronze → silver | 2 |
| Pathfinder's Box | silver → gold | 2 |
| Party Box | bronze → silver | 2 |
| Purist's Box | gold → platinum | 2 |

**30 lists.** At roughly five titles each that is ~150 items — the same order as
the achievement copy, and authored the same way.

## The model

- `achievement.loot_box_type` — which box it drops. Not nullable in practice;
  every achievement drops one.
- `achievement.loot_rarity` — nullable. Null on the boss achievements, where the
  tier supplies it.
- `loot_item` — the authored catalogue: box type, rarity, the title text, and
  whether it was generated rather than written.
- `loot_box` — one awarded box: owner, type, rarity, the achievement that
  dropped it, `opened_at`, and the item it yielded once opened.
- `user.equipped_title_id` — the one title being worn, if any.

A box row carries its own type and rarity rather than looking them up through
the achievement, so re-tiering an achievement later never rewrites what somebody
already holds.

## Opening

Boxes land **unopened** and wait in an inventory. The player opens one by hand.

That is deliberate: the opening is the only ceremony loot has, and resolving it
silently on award throws the whole moment away. It also gives Phase 3 something
to animate.

- Opening picks uniformly from the authored list for that (type, rarity),
  **preferring a title the player does not already hold**.
- **If they hold all of them**, the box still opens and says so plainly. A
  duplicate title is worth nothing, and pretending otherwise is worse than an
  honest empty.
- Opening is idempotent per box: the item is written to the box row, so a
  double-click cannot reroll it. Players would absolutely try.

## The generated tier

**Platinum, legendary and celestial** boxes ask the model for something bespoke
before falling back to the list.

- Generated **on open**, with a short timeout. Any failure — slow, down,
  refused, malformed — falls through to the authored list for that combination,
  which therefore has to be good enough to stand alone. It is not a safety net
  that can be thin.
- Routed through the **existing guardrail layers** (spec 011). This is
  unreviewed model text shown to a player at a work event, which is precisely
  what those layers exist for.
- **Never anything flag-shaped.** `core.md` already forbids the System inventing
  loot, meaning flags; this is the one place the platform deliberately generates
  something *called* loot, so the rule needs restating for it. A generated title
  matching `flag{...}` — or containing a real flag — is rejected and the
  fallback used.
- Generated titles are **stored as catalogue rows marked generated**, so they
  appear in the collection, can be audited afterwards, and can be promoted into
  the authored list if they turn out well.
- Length is capped hard. A title is a few words, and a model given latitude will
  write a paragraph.

Why only the top three tiers: a handful of players reach them, so the volume of
unreviewed text stays small, and the tiers where it matters most are the ones
where a bespoke line is actually a reward.

## Where it shows

- **Scoreboard** — the equipped title beside the display name. The row is
  already a dict; this is one more field.
- **Character sheet** — the collection, and the control to equip one.
- **Notification** — a box landing is a notification like anything else, in the
  System's voice, linking to the inventory.

## Edge cases

- **An achievement re-tiered after boxes have dropped** changes nothing already
  held; the box carries its own type and rarity.
- **A zone with no boss** means its boss achievement is unearnable, so no box.
  Already true of the achievement itself.
- **An empty catalogue for a combination** must be impossible — a seeded list
  per live combination, and a test that every (type, tier) a live achievement
  can produce has items in it.
- **Equipping then deleting** — an item cannot be deleted while worn; the
  catalogue is seed data and admin deletion is out of scope here anyway.
- **The model returning something already in the catalogue** is harmless; it is
  stored once and awarded.
- **A player who never opens anything** keeps a growing inventory. That is
  theirs to deal with, and the count is visible.

## Testing

- Every achievement declares a box type; every live combination has items.
- A box is awarded on achievement award, unopened, with the right type and tier.
- A boss box takes its rarity from the boss tier.
- Opening yields an item, writes it to the box, and is idempotent.
- Opening prefers an unheld title, and says so honestly when all are held.
- A generated title that is flag-shaped is rejected in favour of the fallback.
- A model timeout falls back without an error reaching the player.
- Equipping shows the title on the scoreboard; one at a time.
- Loot moves no score.

## Non-goals

- The visual treatment of opening. Phase 3.
- Admin CRUD over the catalogue. Seeded like the achievement copy; a page can
  follow if it is wanted.
- Trading, gifting, or any economy between players.
- Items with mechanical effects. Cosmetic, permanently.

## Open question

**Do boxes need to be rarer than achievements?** As specced, 117 achievements
means up to 117 boxes, and a median player might open forty. That may be exactly
right — or it may make opening feel like clearing a queue. The alternative is
that only some achievements drop boxes. Recommending one-for-one to start, since
thinning it later is a data change.
