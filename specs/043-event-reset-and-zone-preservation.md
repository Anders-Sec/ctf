# Spec 043 — Event Reset, and Zones That Stay Put

Status: **done** (2026-09-14)
Phase: 2/3 boundary (tooling)
Extends: 042 (bulk operations)
Amends: **013** (category pruning), 040 (the CSV's unknown-category refusal)

Two problems, both hit while setting the real event up, and both the same
underlying thing: **the platform treats test play as permanent, and a zone as
disposable.**

1. A challenge that has been solved cannot be deleted. On the production
   instance that means trial solves from testing now permanently pin challenges
   that were only ever scaffolding.
2. The CSV refuses to import into a zone that does not exist — and zones are
   being *destroyed* by ordinary challenge deletion, which is not obvious from
   anywhere.

## 1. The zone bug

Spec 013 decided that **a category exists exactly as long as something is in
it**, so deleting the last challenge in one deletes the category
([challenges.py:433](../backend/app/services/challenges.py#L433)).

That was right when a category was a string somebody typed into the challenge
form. It stopped being right at spec 018, when 21 categories became **seeded
content** with ability mappings, descriptions and display order
([migration 0021](../backend/migrations/versions/0021_seed_event_content.py)),
and again at 019/021 when they became the dungeon's zones with map positions.

Verified against the real seed: creating one challenge in the seeded
**Networking** zone and deleting it again

- destroys the zone — its name, slug, description, `ability` mapping,
  `display_order` and authored map position,
- detaches its **3 skills**, whose `category_id` is `SET NULL`, so the skill
  picker and the generated `SKILLS.md` lose their grouping,
- and makes `Networking,…` in a CSV fail with *"No category named
  'Networking'"*.

That last line is the symptom that was reported. **The CSV is not the bug.** An
admin who works around it by creating a throwaway challenge gets the zone back —
but recreated from scratch by `resolve_or_create_category`, with `ability` back
to its default and `display_order` 0. The zone is silently no longer the zone the
map and the stat blocks were built around.

### The fix

**Stop pruning. The 21 zones are locked in** — they are the dungeon, and nothing
in ordinary use should remove one.

An empty zone is a perfectly reasonable state: it is what every zone looks like
before its challenges are written, which is exactly the situation the CSV import
exists for. There is **no delete-a-zone endpoint**; a 22nd zone can still be
created by naming one in the challenge editor, but the seeded 21 are fixed
content and removing one is a migration, not a button.

This also removes the warning 042 §4 attaches to bulk delete, and the
`categories_deleted` field it reports, since neither can happen any more. The
field stays in the response shape as an empty list rather than being ripped out
of a just-shipped API.

### Repairing what pruning already did

The production instance has at least one zone that was destroyed and then
recreated by `resolve_or_create_category` — which rebuilds it with a derived
slug, no description, `ability` back to its default and `display_order` 0. The
zone still exists, so nothing looks wrong; it is simply no longer the zone the
map and the stat blocks were built around.

A migration re-asserts the 0021 seed **by name**: description, ability,
display_order and slug set back to what they should be, for every seeded zone,
whether or not it was damaged. It also re-attaches skills whose `category_id`
went `NULL` when their zone was pruned, using 0021's own skill-to-zone mapping.

Idempotent and safe on an undamaged database: it writes the values that are
already there. It deliberately does **not** touch `map_x`/`map_y` — those are
authored in the map editor (spec 021) rather than seeded, so there is nothing to
restore them to, and an admin who has placed a zone should not have it moved.
Any zone that lost its position needs re-placing by hand.

### And the CSV

With pruning gone, the seeded 21 always exist and the reported problem
disappears. The CSV's refusal to invent a category stands as spec 040 wrote it —
a typo must not silently produce a 23rd zone that no map draws and no ability
feeds.

What changes is the **error**, which currently names the typo and stops there.
It should say what an admin can do about it: that zones are created in the
platform, and list the ones that exist. A 242-row file rejected over one unknown
name should not require guessing which name was right.

## 2. Event reset

A new admin operation: **reset play data**. Everything the players did goes;
everything the admins authored, and everyone's account, stays.

### What goes

| Table | Why |
| --- | --- |
| `solve` | The thing that blocks deletion. |
| `submission` | The attempt log. Meaningless once its solves are gone. |
| `hint_unlock` | Purchases. |
| `score_adjustment` | Manual awards, which only make sense against a live board. |
| `achievement_award` | Earned achievements. |
| `notification` | Told to players about things that no longer happened. |
| `player_event` | The platform-event log three achievements read (spec 039). |
| `loot_box` | Awarded boxes. **Not `loot_item`** — see below. |
| `challenge_instance` | Container instances. |
| `challenge_report` | Player-filed broken-challenge reports. |
| `signal_dismissal` | Anti-cheat review state (spec 007). |
| `assistant_conversation`, `assistant_message`, `assistant_finding` | Chat history and guardrail hits (specs 010, 011, 036). |
| `assistant_terms_acceptance` | Consent to the AI's terms. Cleared so a reset event asks again. |
| `class_preference` | A player's class choice (spec 016). |

And on `user`, the columns that are progress rather than identity:
`character_class_id`, `equipped_title_id`, `ai_ladder_level`,
`ai_ladder_leaked_at`, `assistant_blocked`.

**`loot_item` is not play data**, which is not obvious from its name. It is the
*catalogue* of titles a box can yield — 380 of them, seeded — shared by every
player, and even the model-generated entries are kept deliberately so they can be
reviewed and promoted into the authored list (spec 038). Wiping it would delete
authored content. The drop is `loot_box`; the catalogue stays.

`user.equipped_title_id` is still cleared, because nobody should be wearing a
title from a box that no longer exists.

### What stays

Challenges, answers, artifacts, hints, skills, categories, classes, container
templates, unlock requirements, achievements, event config — all authored.

**Users, teams, memberships and sessions** — nobody is logged out and no account
is deleted. A reset is "the event has not happened yet", not "these people do not
exist".

**`audit_log`** — the record of what admins did, including this reset. Wiping the
log as part of an operation that is itself logged would be the one deletion
nobody could review afterwards.

**`broadcast_log`** — what staff announced. Staff action, not play.

### The shape

```
GET  /api/admin/event/play-data         → what every group currently holds
POST /api/admin/event/reset-play-data   → { groups: [...] }
```

The counts are the confirm dialog's content — **1,204 solves · 8,391 submissions
· 212 hint unlocks · …** — so the size of what is about to go is visible before
it goes, per group, with the unticked ones greyed rather than hidden.

This is the one place in this work that earns a real confirmation, and it gets
the strongest one in the codebase: the operator types `RESET`. That is not the
mid-event ceremony this project has rightly refused elsewhere. It is a single
irreversible action across a dozen tables with no undo, and nothing about the
page makes its scale visible until the counts say so.

One audit entry, naming the groups and carrying the counts.

### Scope

**Pick what goes.** An admin selects one or more groups, or takes the lot:

| Group | Tables |
| --- | --- |
| **Solves** | `solve` |
| **Submissions** | `submission` |
| **Hint purchases** | `hint_unlock` |
| **Manual score awards** | `score_adjustment` |
| **Achievements** | `achievement_award` |
| **Notifications** | `notification` |
| **Platform events** | `player_event` |
| **Loot** | `loot_box`, and `user.equipped_title_id` |
| **Container instances** | `challenge_instance` |
| **Challenge reports** | `challenge_report` |
| **Anti-cheat review state** | `signal_dismissal` |
| **AI assistant** | `assistant_conversation`, `assistant_message`, `assistant_finding`, `assistant_terms_acceptance`, `user.assistant_blocked` |
| **AI ladder progress** | `user.ai_ladder_level`, `user.ai_ladder_leaked_at` |
| **Class choices** | `class_preference`, `user.character_class_id` |

Groups rather than raw table names, because the mapping is not obvious and
getting it wrong is destructive: **Loot** means the awarded boxes and everyone's
worn title, and deliberately *not* `loot_item`, which is the shared catalogue.

**Selecting some and not others is allowed, and can leave stale-looking data** —
an achievement earned for a solve that no longer exists, say. That is untidy
rather than broken: everything derived (banked XP, ability scores, skill levels,
boss stars, the board) is computed at read time from whatever is left, so a
partial wipe stays internally consistent even when it reads oddly. The counts say
what each group holds, so the choice is an informed one.

**Solves** on its own is the group that unblocks deleting a challenge.

### Once it has run

Challenges are deletable, because nothing has solved them. The reset is
therefore also the answer to the original request: rather than teaching bulk
delete to destroy solves, the solves are removed deliberately and visibly first,
and the existing refusal keeps protecting real play.

## 3. Non-goals

- **Force-deleting a solved challenge.** The reset is the sanctioned route. A
  `force` flag on bulk delete would make the destructive path the convenient one.
- **Deleting users or teams.**
- **Deleting a zone.** The 21 are locked in; a 22nd can still be created by
  naming it in the challenge editor, but nothing removes one.
- **Undo.**

## 4. Testing

- Deleting the last challenge in a zone **leaves the zone**, its ability, its
  display order and its skills' grouping intact.
- A CSV then imports into that empty zone.
- An unknown category still refuses, and the error names the zones that exist.
- Bulk delete no longer reports `categories_deleted`.
- The seed-repair migration restores a zone whose ability and display order were
  reset, re-attaches its orphaned skills, and changes nothing on an undamaged
  database.
- The play-data counts report each group without writing anything.
- Resetting one group empties that group and leaves every other one alone.
- Resetting everything empties every listed table, and leaves challenges,
  categories, skills, users, teams, sessions and the audit log untouched.
- Wiping loot removes the awarded boxes, unequips every worn title, and leaves
  the `loot_item` catalogue untouched.
- `user.character_class_id`, `equipped_title_id`, `ai_ladder_level`,
  `ai_ladder_leaked_at` and `assistant_blocked` are cleared.
- A challenge that could not be deleted before the reset can be after it.
- The reset writes exactly one audit entry carrying the counts.
- Only admins may preview or run it; staff are refused.

## 5. Decisions (2026-09-14)

1. **The reset is per-group, not all-or-nothing**, with a select-everything
   option. §2 lists the groups.
2. **`score_adjustment` and `assistant_terms_acceptance` are their own groups**,
   which is what the earlier open questions about them were really asking — the
   answer is per-run rather than fixed in the spec.
3. **The 21 zones are locked in.** No delete-a-zone endpoint, and pruning stops.
   A migration repairs what pruning already damaged on production.
