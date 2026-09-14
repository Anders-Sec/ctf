# Spec 043 — Event Reset, and Zones That Stay Put

Status: **draft** (awaiting sign-off)
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

**Stop pruning.** A category is authored content now; deleting a challenge must
not delete one.

An empty zone is a perfectly reasonable state — it is what every zone looks like
before its challenges are written, which is exactly the situation the CSV import
exists for. Removing a zone becomes a deliberate admin action with its own
endpoint, refused while it still holds challenges.

This also removes the warning 042 §4 attaches to bulk delete, and the
`categories_deleted` field it reports, since neither can happen any more. Both
stay in the response shape for one release as an empty list rather than being
ripped out mid-flight.

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
| `loot_box`, `loot_item` | Drops and their one-of-a-kind titles (spec 038). |
| `challenge_instance` | Container instances. |
| `challenge_report` | Player-filed broken-challenge reports. |
| `signal_dismissal` | Anti-cheat review state (spec 007). |
| `assistant_conversation`, `assistant_message`, `assistant_finding` | Chat history and guardrail hits (specs 010, 011, 036). |
| `assistant_terms_acceptance` | Consent to the AI's terms. Cleared so a reset event asks again. |
| `class_preference` | A player's class choice (spec 016). |

And on `user`, the columns that are progress rather than identity:
`character_class_id`, `equipped_title_id`, `ai_ladder_level`,
`ai_ladder_leaked_at`, `assistant_blocked`.

`equipped_title_id` has to be cleared **before** `loot_item` goes or it dangles;
the FK is `SET NULL`, so the database would cope, but doing it in the wrong order
leaves a window where the scoreboard renders a title that is being deleted.

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
POST /api/admin/event/reset-play-data/preview   → counts per table
POST /api/admin/event/reset-play-data           → does it
```

The preview is the confirm dialog's content: **1,204 solves · 8,391 submissions ·
212 hint unlocks · …**, so an admin sees the size of what they are about to
remove. This is the one place in this work that earns a real confirmation, and it
gets the strongest one in the codebase: the operator types the word `RESET`.

That is not the mid-event ceremony this project has rightly refused elsewhere.
It is a single irreversible action across a dozen tables with no undo, and unlike
deleting a challenge, nothing about the page makes its scale visible until the
preview says so.

One audit entry, with the counts in its metadata.

### Scope

Everything, or nothing. **No per-challenge or per-player reset** — a partial wipe
leaves derived state (banked XP, ability scores, achievement progress) referring
to solves that are gone, and every one of those is computed at read time from
tables this would leave half-empty. A whole reset is coherent by construction; a
partial one needs a consistency argument per table, which is a much bigger
feature than the problem justifies.

### Once it has run

Challenges are deletable, because nothing has solved them. The reset is
therefore also the answer to the original request: rather than teaching bulk
delete to destroy solves, the solves are removed deliberately and visibly first,
and the existing refusal keeps protecting real play.

## 3. Non-goals

- **Force-deleting a solved challenge.** The reset is the sanctioned route. A
  `force` flag on bulk delete would make the destructive path the convenient one.
- **Deleting users or teams.**
- **Partial resets.**
- **Undo.**

## 4. Testing

- Deleting the last challenge in a zone **leaves the zone**, its ability, its
  display order and its skills' grouping intact.
- A CSV then imports into that empty zone.
- An unknown category still refuses, and the error names the zones that exist.
- Bulk delete no longer reports `categories_deleted`.
- Deleting a category is refused while it holds challenges, and succeeds when
  empty.
- The reset preview counts each table without writing anything.
- The reset empties every table in the list, and leaves challenges, categories,
  skills, users, teams, sessions and the audit log untouched.
- `user.character_class_id`, `equipped_title_id`, `ai_ladder_level`,
  `ai_ladder_leaked_at` and `assistant_blocked` are cleared.
- A challenge that could not be deleted before the reset can be after it.
- The reset writes exactly one audit entry carrying the counts.
- Only admins may preview or run it; staff are refused.

## 5. Open questions

1. **Does `score_adjustment` go?** It is admin action rather than play, which
   argues for keeping it with the audit log — but an award of +500 against a
   board that has been reset to zero is a scoreboard nobody can explain.
   Recommend **wiping it**, and noting that the audit log still records every
   adjustment that was made.
2. **Does `assistant_terms_acceptance` go?** Clearing it makes every player
   re-accept, which is right for a genuine reset and annoying if the reset is
   being used to clear a test run mid-preparation. Recommend **wiping it** — the
   acceptance is part of the run, and re-accepting costs one click.
3. **Should removing a zone be possible at all?** This spec adds
   `DELETE /api/admin/categories/{id}`, refused while non-empty, to replace what
   pruning used to do by accident. If zones are fixed content for this event,
   that endpoint can simply not exist. Recommend adding it — the 21 seeded ones
   are not sacred and an admin who wants 20 should not have to write SQL.
