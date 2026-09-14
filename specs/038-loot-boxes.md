# Spec 038 — Loot Boxes

Status: **done** (2026-09-14) — logic and content shipped; the visual treatment of an opening is Phase 3
Phase: 2 (D&D Mechanics), with the visual treatment deferred to Phase 3
Depends on: 029 (the achievement roster), 031 (boss tiers), 028 (notifications)

Most achievements drop a box. The box has a **type** and a **rarity**, and that
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

## Not everything pays out

**81 of the 117 achievements drop a box. The other 36 get a line instead**,
explaining why the System is not rewarding this one — because the act is its own
reward, because it was a cheat attempt, or because it was simply too small.

That split is most of what keeps loot from feeling like a queue. It also lets
the negative achievements land harder: *Reading Comprehension* is funnier when
it comes with nothing in it.

Which get nothing: wrong answers that are merely wrong rather than impressive
(`bad_start`, `literally`, `warming_up`), attempts to talk the System out of a
flag (`nice_try`, `undeterred`), small talk (`manners`, `existential`), party
churn (`second_thoughts`, `asked_to_leave`), machinery noise that was not the
player's doing (`it_was_like_that`), and aimless progress (`wide_not_deep`,
`identity_crisis`).

Which still pay out despite being unflattering: the spectacular ones.
`brute_force_strategy` — one hundred wrong flags — earns a Gold Brute Force Box,
because at that volume it has stopped being a mistake and become a method.
`obsession`, `no_variation` and `you_broke_it` likewise.

A no-box achievement carries a `no_loot_line`: one sentence from the System, in
the same voice as everything else, delivered with the achievement notification
rather than as a second message.

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

### Rarity is quality, not just colour

A bronze title is deliberately dull. The tier is a statement about how good the
title *sounds* — the only axis available, since nothing here has a mechanical
effect. Bronze is administrative; celestial is something a player will want on
the board for the rest of the event.

That means effort is not spread evenly. The high tiers are where the writing
matters and where the player's attention is, and the content budget should
follow.

### Pools are shared at the bottom

A bronze Adventurer's Box and a bronze Brute Force Box are both boring, and
there is no reason to invent two sets of boring titles.

- **Bronze is one shared pool** across every box type.
- **Silver shares across a couple of families** — progress-shaped types draw
  from one, mischief-shaped types from another.
- **Gold and above are per box type**, because that is where the box's identity
  should actually come through.

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

Against the 81 box-dropping achievements that is **35 live (type, tier)
combinations, 12 of them platinum or above**.

Sharing collapses the bottom further: one bronze pool and two silver families
replace what would otherwise be a dozen near-identical lists. The remaining
effort concentrates where the recommendation below puts it — the twelve
high-tier combinations, which is also where the players are looking.

## The model

- `achievement.loot_box_type` — which box it drops. **Null means it drops
  nothing**, and `no_loot_line` carries what the System says instead.
- `achievement.loot_rarity` — nullable. Null on the boss achievements, where the
  tier supplies it, and on the 36 that drop nothing.
- `achievement.no_loot_line` — the System's sentence for a no-box achievement.
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

- Opening picks uniformly from the pool for that (type, rarity), **preferring a
  title the player does not already hold**.
- **Platinum and above are one of a kind.** Once a title at those tiers is
  awarded to anybody, it is never offered again. Two identical legendary titles
  side by side on the scoreboard would undo the whole point of them.
- Bronze, silver and gold may repeat across players. They are common by design,
  and the shared pools guarantee it.
- **If a player holds every title in a low-tier pool**, the box still opens and
  says so plainly. A duplicate is worth nothing and pretending otherwise is
  worse than an honest empty.
- Opening is idempotent per box: the item is written to the box row, so a
  double-click cannot reroll it. Players would absolutely try.

## The generated tier

**Platinum, legendary and celestial** boxes ask the model for something bespoke
before falling back to the list.

- Generated **on open**, with a short timeout. Any failure — slow, down,
  refused, malformed — falls through to the authored list for that combination,
  which therefore has to be good enough to stand alone. It is not a safety net
  that can be thin.
- Generation is also what **absorbs exhaustion**. High tiers are unique, so a
  popular platinum achievement earned by fifty players needs fifty distinct
  titles, and a fixed list will run out. A generated title is unique by
  construction.
- **If generation fails *and* the authored pool is exhausted**, the box refuses
  to open and says to come back. It does not hand out a duplicate to save face,
  and the player loses nothing. This is the one place the feature is allowed to
  say "not now".
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

**How deep should the platinum-and-above pools be?** This is the dial between
the model being a bonus and the model being load-bearing.

Shallow pools (say ten per combination) mean a popular platinum achievement
exhausts quickly and most high-tier titles come from the model — fresher, but
high-tier boxes stop opening whenever it is down. Deep pools (twenty-five or
more) keep uniqueness working on authored content alone for realistic player
counts, and the model becomes flavour on top.

Recommending **deep**: roughly twenty-five per platinum+ combination, which is
where the writing effort should go anyway. It puts the content total near 250
titles, most of them at the tiers players care about.
