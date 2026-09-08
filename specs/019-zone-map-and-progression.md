# Spec 019 — The Zone Map & Category Progression

Status: **draft** (2026-09-08) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Depends on: 017 (map, zone gating, unlock evaluator), 018 (categories, abilities)
**Amends** 017: the map becomes a map of *zones*, not of every challenge.

Later specs shift again: boss encounters and loot become 020/021.

## Why

017 drew a room per challenge. At 231 challenges that is unreadable, and it makes
an *artistic* map impossible — you cannot illustrate 231 things. The map becomes
**22 zones**; clicking one opens that zone's challenges.

That also gives the dungeon a shape worth drawing, because the progression below
is a real graph with three tiers rather than a flat wall of content.

---

# Part 1 — The progression graph (locked in)

A new **Intro** category (the 22nd) is the only thing open at the start: a single
getting-started challenge that opens the first wave.

| Zone | Opens when |
| --- | --- |
| **Intro** | Open from the start |
| Networking | Intro cleared |
| Governance, Risk & Compliance | Intro cleared |
| Hacker Game Show | Intro cleared |
| CTI | Intro cleared |
| Incident Response | Intro cleared |
| AI/LLM Security | Intro cleared |
| Cloud Security | **25%** of Networking |
| OSINT | **50%** of CTI |
| Forensics | **25%** of Incident Response |
| Threat Detection | **50%** of Incident Response |
| Prompt Injection | **50%** of AI/LLM Security |
| Codes and Ciphers | **25%** of Hacker Game Show |
| Crypto | **25%** of Hacker Game Show |
| **Red teaming** | Player **level 5** |
| Hardware Hacking | **25%** of Red teaming |
| Social Engineering | **25%** of Red teaming |
| Identity & Access | **50%** of Red teaming |
| Web Attacks | **50%** of Red teaming |
| Mobile Security | Player **level 8** |
| Reverse Engineering | Player **level 8** |
| Malware Analysis | Player **level 8** |

Verified: all 21 real categories appear exactly once, every zone is reachable from
Intro, and there are no cycles. The graph is three tiers deep — Intro, then the
six it opens plus the three level-gated wings, then everything those open.

**One thing to confirm:** you said Intro gates "the first 7", but listed six
(Networking, GRC, Hacker Game Show, CTI, Incident Response, AI/LLM Security).
Built as six, with Intro itself as the seventh area. Say if a seventh belongs in
that first wave.

## Two new gate types

017's four types cannot express this. Two more:

| Type | Means | Needs |
| --- | --- | --- |
| `percent_in_category` | Clear a share of a zone | `required_category_id`, `threshold` (a percentage) |
| `player_level` | Reach a player level | `threshold` (the level) |

`percent_in_category` is measured against the challenges in that category the
player **can see**, so unreleased content does not make a gate unreachable.

`player_level` could be faked with `min_xp` (level 5 is 2,000 XP), but the gate
should say what it means — and if the XP curve is ever retuned, a level gate
follows it while a hard-coded XP number silently drifts.

## The re-locking hazard, and sticky unlocks

A percentage gate has a trap a count does not. A player clears 6 of 11 in a zone
(54%) and opens the next one. An admin then adds 3 challenges. The player is now
on 6/14 — 43% — and **the zone they earned slams shut**.

That is unacceptable mid-event, and adding challenges mid-event is normal.

So **zone unlocks are sticky**: the first time a player satisfies a zone's
requirements, that is recorded, and the zone stays open forever after. Evaluation
becomes *"the live condition is met **or** it was met before"*.

- New table **`zone_unlock`** — `user_id`, `category_id`, `unlocked_at`, unique
  per pair.
- Written whenever a zone evaluates as unlocked and no row exists yet.
- Applies to zone gates only. Individual challenge prerequisites are unaffected —
  those are `challenge_solved`, which can never regress.

This also makes the map honest: a zone that has ever opened is drawn as open.

---

# Part 2 — The map becomes a map of zones

- **`GET /api/map`** returns **22 zone nodes**, not 231 rooms: id, name, ability,
  locked, unlock requirements, cleared/total, and its edges to the zones it opens.
- **Edges are the progression graph**, so the corridors finally mean something:
  they are what opens what.
- **Clicking a zone** opens its challenge list — a panel, not a new page, so the
  map stays put behind it. That list is the existing challenge board filtered to
  one category, with the same locked/solved treatment.
- The **list view** stays a complete equivalent of everything, unchanged.
- **Zone positions become authored.** With 22 nodes, hand-placing them on
  illustrated art is both feasible and the point; a derived fallback still applies
  to any zone without a position, so a new category can never vanish.

## Testing

- The graph seeds exactly as documented, and every zone is reachable from Intro.
- A percentage gate opens at the threshold and is measured against visible
  challenges only.
- **The re-lock test:** a player who has opened a zone keeps it open after new
  challenges are added to the zone that gated it.
- A `player_level` gate opens at the level, and follows the XP curve rather than a
  frozen XP number.
- The map returns zones, not challenges, and the leak rules from 017 still hold:
  no zone reveals a challenge the player may not see.
- Zone cleared/total counts only challenges the player can see.

## Commit plan

1. Schema: `zone_unlock`, the two new requirement types, the Intro category.
2. The evaluator: percentage and level gates, plus sticky unlock recording.
3. Seed the progression graph.
4. `GET /api/map` returns zones with edges; zone drill-down endpoint.
5. Frontend: the zone map and the challenge panel.

## Non-goals

- **The artwork itself** — this spec makes the map *drawable* (22 nodes, authored
  positions, a real graph). How it is drawn is the next conversation.
- Boss encounters and loot (020/021).
