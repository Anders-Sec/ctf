# Spec 024 — The Class Roster

Status: **approved** (2026-09-08)
Phase: 2 (D&D Mechanics)
Depends on: 016 (the class system), 018 (abilities, skills, XP economy)

016 built the class machinery and shipped it empty — `character_class` has zero
rows, so a player who reaches the unlock level today is offered nothing. This
fills it from the roster in `Ideas.md`, and adds the three things that roster
needs which the current model has no room for: **rarity**, **preference
targets**, and **unlock requirements**.

## What changes in the model

`character_class` today has name, display order and description. Three additions:

**Rarity** — an enum on the class: `common`, `uncommon`, `rare`, `legendary`,
`mythic`. It affects **colour and nothing else** — no scoring, no gating, no
ordering. Rarity is a label on how hard the class was to reach, which the unlock
requirements already enforce on their own.

**Preference targets** — what the recommender matches a player against. The
roster mixes two kinds: the D&D-named classes point at **abilities** (Barbarian →
STR, CON), the cyber-named ones at **skills** (Sysadmin → Packet Whispering,
Cloud Instinct). One child table with a nullable `ability` and a nullable
`skill_id`, exactly one set — the same XOR shape as `unlock_requirement`, for the
same reason.

**Unlock requirements** — every requirement in the roster is a skill-level
threshold, and Mythic classes carry two or three of them. A small dedicated
table (`class`, `skill_id`, `min_level`) rather than extending
`unlock_requirement`: that table's whole surface is six gate types and a
challenge-XOR-category target, and none of the other five apply here. Narrow now,
extensible later if a class ever needs an XP or player-level gate.

## Reading the roster

The tier headings in `Ideas.md` — "Tier 1 (Levels 5-8)", "Tier 3 (Level 13+)" —
describe the **skill** levels in each tier's requirements, not a player level.
Tier 1's requirements are skill levels 5–8, Tier 3's are 13–15, and so on. Class
availability is therefore governed by two independent things: the existing
overall-level gate from 016 (`class_unlock_level`, currently **5**) which decides
whether a player may pick a class at all, and these per-class skill thresholds
which decide *which* classes are on offer.

48 classes: 30 common, 6 uncommon, 5 rare, 3 legendary, 4 mythic. All 28 skills
the roster references exist in the seeded set — checked, none missing.

## The recommender

016 described the suggestion as "the class whose affinity skill is the player's
highest-XP skill". 018 deleted the affinity skill, so this replaces it.

Raw values cannot be compared across the two kinds of target: an ability pools
several categories, so ability XP is always far larger than any one skill's, and
a naive sum would hand every recommendation to the D&D classes. So each target is
scored as a **fraction of the player's own best in that dimension** — this skill
against their strongest skill, this ability against their strongest ability — and
a class scores the **mean of its targets**. That asks "which of these is this
player relatively strongest in", which is comparable across both kinds and needs
no tuning constant.

- Only classes the player has **unlocked** are recommended.
- Ties break on rarity (rarer first — it is the more interesting suggestion),
  then display order.
- A player with no XP at all gets no suggestion, as today.
- The System AI's delivery of the nudge (spec 016) is unchanged; it just gets a
  better answer to read out.

## Locked classes are invisible

A class a player has not unlocked **does not appear at all** — no greyed entry,
no requirement text, no count that would reveal one exists. The roster is meant
to be a mystery, and discovering a class you did not know about is the payoff.

This is deliberately the opposite of the zone rule in 017 and 019, and the reason
they differ is worth stating: a sealed *zone* is visibly there on the map, so
hiding its condition would only frustrate — the player can see the door. A locked
*class* is not visible at all, so there is no door to be frustrated by.

Consequences that fall out of it:

- The recommender only ever names an unlocked class, which it already did.
- The picker lists unlocked classes only. Nothing displays a total, since "30 of
  48" would give the game away.
- Admins still see the whole roster, requirements included — they are authoring
  it.
- **A newly unlocked class currently arrives silently**, appearing in the picker
  with no announcement. Announcing it is the achievement system's job and is out
  of scope here; this is a known gap, not an oversight.

## A reachability problem worth deciding on

Skill level costs `70 × (L-1)^1.25` XP, and 018 budgets roughly **2000 XP per
category**. Against that budget the top of the roster is very expensive:

| Class | Needs | XP in that one skill | Share of a category's whole XP |
| --- | --- | --- | --- |
| Packet Sage | Packet Whispering 5 | 396 | 20% |
| Breachwright | Exploit Crafting 8 | 798 | 40% |
| Cryptomancer | Cryptanalysis 10 | 1092 | 55% |
| Root Ascendant | Privilege Escalation 13 | 1564 | 78% |
| The Unwritten | Disassembly 14 | 1728 | 86% |
| Herald of Zero-Day | Exploit Crafting 15 | 1896 | 95% |

Skills overlap — a challenge feeds **every** skill attached to it in full — so
these are reachable, but only if the skill is attached to nearly every challenge
in its home category *and* the player clears nearly all of them. Herald of
Zero-Day at 95% effectively means "clear the entire category, with Exploit
Crafting on every challenge in it".

That is a **content-authoring constraint, not a bug**: whether the legendary
classes are attainable is decided by how skills get attached, which is the same
lever that makes them attainable at all. But it should be a decision rather than a
surprise found during the event. Options:

1. **Leave it.** Legendary and Mythic are meant to be nearly unreachable; one or
   two players managing it is the point.
2. **Lower the top thresholds** to 10–12, putting Legendary at 55–70% of a
   category — hard, but not requiring a clean sweep.
3. **Soften the skill curve** (raise `skill_level_base`'s effect or lower the
   exponent) so high skill levels cost less. Affects everything reading skill
   levels, including zone gates — the widest blast radius.

Recommendation: **(1) for now**, revisit once real challenge content exists and
the actual per-skill XP is measurable. Nothing here is hard to change later; the
thresholds are seed data.

## Rarity colours

Five tokens in `index.css` alongside the existing palette, so the coming UI
overhaul owns them: common (stone), uncommon (green), rare (blue), legendary
(amber/torch), mythic (violet). Colour is never the only signal — the rarity name
is always present as text, so this survives greyscale and screen readers.

## Testing

- All 48 classes seed, with the right rarity, targets and requirements.
- A class whose requirements are unmet is locked, and says what it needs.
- Meeting the last requirement unlocks it.
- A multi-requirement Mythic class needs *all* of its thresholds, not any.
- The recommender does not favour ability-target classes over skill-target ones
  for a player equally strong in both.
- Only unlocked classes are recommended.
- Rarity affects presentation only: it appears in no gate and no score.
- A locked class is absent from the player-facing roster entirely — not greyed,
  not counted — while an admin still sees it.

## Decisions

1. **`class_unlock_level` stays 5.** No change; the config is already correct.
2. **Locked classes are invisible**, per the section above.
3. **Reachability: leave the thresholds as they are**, and revisit when real
   challenge content exists and per-skill XP can be measured. Hiding locked
   classes makes this safer than it was — an unreachable class is simply one
   nobody ever sees, rather than a visible goal that taunts.
4. **A class once chosen is kept**, matching 016's rule for the overall-level
   gate. Skill XP is banked and monotonic, so a skill level cannot fall anyway.

## Non-goals

- Class abilities, bonuses, or any scoring effect — 016's hard rule stands.
- Boss/loot hooks that read class; those specs define their own.
- Narrative flavour text per class — the Phase 3 writing pass.
