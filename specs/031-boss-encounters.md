# Spec 031 — Boss Encounters

Status: **done** (2026-09-13)
Phase: 2 (D&D Mechanics)
Depends on: 019 (zones), 028 (notifications and achievements), 029 (the roster)
Pairs with: 032 (broadcasts — a boss first kill is its motivating case)

A boss is one challenge per zone, chosen by an admin because it is *the fight in
that wing*. Beating it earns a star on your profile, coloured by the boss's
tier, and an achievement.

## Why a flag and not a difficulty

The platform already knows how hard a challenge is, and already notices a
nearly-impossible solve (`against_the_odds`). If a boss meant "nearly
impossible" it would be a synonym and would earn nothing.

A boss is an **editorial judgement the ladder cannot make**: the AI Prompt
Injection challenge is a boss because of where it sits in the story of its wing,
not because of its points. So the flag is admin-set, per zone, and deliberately
scarce.

## The model

One nullable column on `challenge`:

```
boss_tier: BossTier | None   -- null means "not a boss"
```

A separate `is_boss` boolean would be a second source of truth for the same
fact, and the two would eventually disagree.

### The tiers

| Level | Name | Star colour |
| --- | --- | --- |
| 1 | Neighborhood Boss | Bronze |
| 2 | Borough Boss | Silver |
| 3 | City Boss | Gold |
| 4 | Province Boss | Platinum |
| 5 | Country Boss | Legendary (orange/red) |
| 6 | Floor Boss | Celestial |

Tier is chosen by the admin and is independent of difficulty — a Neighborhood
Boss in a late wing may be harder than a City Boss in an early one, and that is
the point.

**Celestial** is a pale iridescent violet-white — it reads as "above legendary"
without turning into a second gold, and it is the one tier with no real-world
metal to borrow from.

The tier names already carry their loot-box names in your notes
(Bronze Boss Box … Celestial Boss Box). Those are recorded here but nothing in
this spec uses them; they are the hook the loot work will read.

### One boss per zone

Enforced with a partial unique index on `category_id` where `boss_tier` is not
null.

This is a real constraint and worth being sure about: it makes "the boss of this
area" exact, which is what lets the achievement key on the zone rather than the
challenge. Relaxing it later is a one-line migration; tightening it after two
bosses exist in one zone is not.

## The star

**Derived, never stored.** A star is "you have a solve on a challenge that
carries a boss tier". There is no award table, nothing to keep in sync, and no
backfill problem — flagging a boss after people have beaten it gives them their
stars immediately, which matters while the roster is still being set up.

It also reads from the **solve**, not from the challenge's current state. If a
broken boss is disabled mid-event, the people who already killed it keep their
stars. Taking a star back because an admin fixed something would be the worst
possible behaviour.

Shown in two places:

- **The character sheet** — a row of stars, grouped by tier, each naming its
  boss.
- **The scoreboard row** — a compact star count. The board is where people
  actually look, and the entry is already a dict, so this is one more field.

## The achievement

Every boss also has an achievement, per DCC.

The achievement **keys on the zone, not the challenge**: code `boss_<zone-slug>`,
trigger "solved whichever challenge in this zone carries a boss tier". Swapping
which challenge is the boss during preparation then changes nothing about the
achievement, its code, or anything already awarded.

22 placeholders are seeded now — one per zone — with the same
`TODO: System AI flavour text.` description every other achievement carries, to
be renamed and themed later. A zone that never gets a boss simply has an
achievement nobody can earn, which is the same inert state 029 already tolerates.

## The map

A zone holding a boss is marked on the dungeon map. It is nearly free — the map
already draws every zone — and it is the cheapest narrative win available: a
wing with something waiting in it reads differently from a wing that merely
ends.

## Admin

The challenge editor gains a tier picker: "not a boss" plus the six levels. The
challenges list marks bosses so the set is reviewable at a glance, since the
whole point is that there are few of them and they are chosen deliberately.

Setting a tier on a challenge in a zone that already has a boss is refused, and
the error names the challenge already holding the slot.

## Scoring

**None.** A boss awards no XP beyond its own value as a challenge, and stars do
not rank. Difficulty already makes a hard boss worth more. This holds the line
015 and 016 both drew: identity never touches the scoreboard.

## Edge cases

- **A boss challenge that is unpublished or disabled** keeps its stars and its
  achievement for everyone who already beat it, and simply stops being
  beatable.
- **Changing a boss's tier after kills** changes the colour of everyone's star
  for it. Correct: the star describes the boss, not the moment.
- **Moving a challenge to another category** carries its boss flag, which could
  collide with that zone's existing boss. Refused, same as setting it directly.
- **A zone with no published challenges** cannot have a boss; the picker has
  nothing to offer.

## Testing

- A tier can be set and cleared; null means not a boss.
- A second boss in the same zone is refused, naming the incumbent.
- A star appears for a solved boss and is coloured by its tier.
- Disabling a boss challenge does not remove anybody's star.
- Flagging a boss after the fact gives prior solvers their star immediately.
- The zone achievement awards on solving that zone's boss, whichever challenge
  it is.
- Stars and boss kills award no XP and do not move the scoreboard.
- Only admins may set a tier.

## Non-goals

- Loot boxes. The tier names anticipate them; nothing here implements them.
- Boss-specific mechanics — timers, attempts, phases. A boss is a challenge.
- Party or team boss credit. Stars are per player, like everything else.
- Broadcasting the first kill. That is 032, and this ships without it.
