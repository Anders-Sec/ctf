# Spec 046 — One container, several challenges, a flag each per team

Status: **draft** — awaiting sign-off
Phase: platform (amends 009, completes 008 Decision 6)
Covers: the prerequisite `045-web-apothecary-container.md` records, and the same
prerequisite for the `web-registry` image after it
Depends on: 009 (`container_template`, `challenge_instance`, the launcher, the
per-owner cap), 003 (`MatchType`, the answer-rule registry, the submission path)

## Purpose

Let several challenges be served by **one** running container, and give each of
those challenges **its own flag, unique to the team that launched it**.

A team opens the apothecary from the IDOR challenge. One container starts,
carrying four flags that belong to them alone. They solve the IDOR, move to the
SQL injection in the same environment, then the traversal, then the template
injection. When the fourth falls, the container winds down and they launch the
registry for the next four.

Two changes make that work, and they are specified together because each is
unsound without the other:

- **Sharing.** Spec 009 keyed an instance to a challenge, which was right when a
  container was one challenge's target. Both Web Attacks images are one image
  carrying four challenges, by hard constraint of the sandbox infrastructure. As
  built, a team playing the apothecary launches four identical pods and is
  refused the third by `INSTANCE_MAX_PER_OWNER` (2).
- **A flag per challenge, per instance.** Spec 009 gives an instance one
  `generated_answer`. Four challenges sharing one string means the first solve
  hands over the other three. Sharing without this is broken; this without
  sharing has nowhere to live.

Done when a team can launch the apothecary from any of its four challenges, reach
the same target from the other three, submit four different flags that no other
team can use, spend one slot of their cap rather than four, and have the
container wind down shortly after the fourth solve.

## Flags: an authored stem with a per-team tail

A flag is the authored string with a hex tail:

```
flag{not_your_chart_a3f9c1d0}
flag{quotes_are_load_bearing_5b2e77af}
```

The stem is the flavour the challenge author wrote and it survives. The tail is
what makes a screenshot in a group chat worthless to the team that receives it.

**Every challenge gets its own tail.** One tail per instance, shared across its
four challenges, would be a disaster dressed as a simplification: the stems are
the challenge titles, so a team that solved the easy IDOR would read
`flag{not_your_chart_a3f9c1d0}`, and type `flag{up_and_out_a3f9c1d0}` into the
hard one without launching an exploit. Tails are drawn independently per
(instance, challenge).

Tail: eight lowercase hex characters, `secrets.token_hex(4)`. Guessing is not the
threat — submission rate limiting from 003 already handles that — and eight keeps
a flag short enough to retype off a terminal without hating us.

Comparison casefolds both sides before the constant-time compare, matching the
`case_insensitive` default every other flag in the event uses. A player who types
the tail in caps has still solved the challenge.

## The `dynamic` match type

`MatchType` gains `DYNAMIC`, which is the type the model comment has been
reserving since 003: *"spec 009 will add a computed per-instance type that fits
the same column shape."* It does.

- The rule's `value` is **the stem**, without the `flag{}` wrapper:
  `not_your_chart`.
- Its resolver always returns no-match and never errors. It cannot see an
  instance, and `app/services/answers.py` is a pure registry that must stay that
  way. The rule is a *declaration* that this challenge's flag is minted per
  instance; the matching happens on the instance path below.
- Validation at save: the stem matches `[a-z0-9_]{1,64}`, so the minted flag is
  always well-formed, and a `dynamic` rule requires the challenge to have a
  `container_template_id` — a dynamic flag with no container is a challenge
  nobody can ever solve, and that is worth refusing at save rather than
  discovering at the event.

Using a rule rather than a new column is what keeps this small: the CSV importer
and exporter, the challenge editor, the answer-rule admin and the import/export
round-trip all already carry answer rules with types and values. A column would
mean touching every one of them.

**The CSV spelling** is therefore `[{"type": "dynamic", "value": "not_your_chart"}]`
in the `flags` column, with the plain `flag` column left empty. See
`Challenge/dynamic-flags-note.md`, which is the version of this sent to the
session that owns the challenge rows.

## Data model

Migration `0045_per_challenge_instance_answers`:

**New table `challenge_instance_answer`** — one row per (instance, challenge):

| Column | Notes |
| --- | --- |
| `instance_id` | FK → `challenge_instance`, `ON DELETE CASCADE` |
| `challenge_id` | FK → `challenge`, `ON DELETE CASCADE` |
| `value` | the minted flag, plaintext, as every other answer is stored |
| — | `UNIQUE (instance_id, challenge_id)` |

**`challenge_instance.generated_answer` is dropped**, its values migrated into
the new table as a single row each. One mechanism, not two: a column that means
"the answer, if there is exactly one" alongside a table that means "the answers"
is the kind of duplication that gets one of them forgotten in a later change.
Instances are ephemeral, so the data migration is a formality.

**`container_template.shared_instance`**, boolean, default `false`. False is
exactly today's behaviour, byte for byte.

### Sharing is explicit, not inferred

Two challenges pointing at the same template *could* be taken to mean "share the
instance" with no new column. Rejected: it would silently change behaviour for
every existing template the moment two challenges happened to point at one, which
is a live-event surprise rather than a feature. An operator binding a second
challenge to a single-challenge template should get what they asked for.

`shared_instance` and `injects_answer` are now **compatible** — together they are
the whole feature. (An earlier draft of this spec had them mutually exclusive,
which was the right reading of a one-answer instance and is the thing this
version changes.)

## Minting, at launch

`launch` already loads the template. It now also loads **every published
challenge bound to that template** and mints a flag for each into
`challenge_instance_answer`. All of them, not just the one the player launched
from — the container is handed all four at once and cannot be topped up later,
and a player is free to work them in any order.

Unpublished siblings are skipped. A challenge published *after* an instance
launched has no flag in that instance; the player relaunches, which the TTL makes
happen anyway. Called out here because it is the one gap, and it only exists if
staff publish mid-event.

## Delivery to the container

One environment variable, `INSTANCE_ANSWERS`, holding a JSON object keyed by
challenge **slug**:

```json
{"someone-elses-chart": "flag{not_your_chart_a3f9c1d0}",
 "quotes-are-load-bearing": "flag{quotes_are_load_bearing_5b2e77af}"}
```

Slug-keyed because a slug is stable across a retitle and is already the CSV's
match key. One variable rather than one per challenge because it needs no name
mangling and no guessing at what a slug becomes in shell.

`INSTANCE_ANSWER` — 009's single variable — is still set when the template serves
exactly one challenge, so the demo image and any future single-challenge image
are untouched.

### The obligation this puts on the image

**An image that carries a file-read or command-execution challenge must
materialise its flags and then scrub `INSTANCE_ANSWERS` from its environment
before serving a single request.**

This is not decoration. The apothecary's path-traversal challenge can read
`/proc/self/environ`. If the flags are still in the environment when gunicorn
starts, that `hard` challenge hands over the `very_hard` challenge's flag, which
is the exact leak `Challenge/container-web-apothecary.md` told us to prevent and
that 045 guards against elsewhere. The entrypoint reads the variable, writes the
flags where they belong, unsets it, and `exec`s the server, which inherits the
scrubbed environment.

The platform cannot enforce this — it is a property of the image — so it is
stated here as a contract and implemented per image. 045 carries it for the
apothecary.

## Submission

`answer_matches` keeps its signature and changes its body: find the submitting
player's live instance **for that challenge's template**, then look up the
`challenge_instance_answer` row for (that instance, that challenge), then compare
casefolded and constant-time.

The call site in `challenges.py` is unchanged, including its ordering: static
rules are checked first and the instance answer only when they miss, so a
challenge can still carry both a fixed and a per-team flag. The container
challenges carry only the dynamic one.

A player with no live instance cannot match, which is correct — there is nothing
for them to have solved. A player submitting another team's flag does not match,
which is the point of the whole spec.

## The launcher change

`backend/app/services/instances/launcher.py`, three lookups, each a swap from
"this challenge" to "this template, when the template says so":

1. **`launch` reuse.** Today: return the live instance whose `challenge_id`
   matches. New: if the template is shared, match on `template_id` instead. This
   is what keeps the cap at one slot for a whole area — the second, third and
   fourth launch are the idempotent-reuse path that already exists, reached by a
   wider match.
2. **`find_for_owner`.** The `GET`, `DELETE` and `extend` target, so all three
   follow.
3. **`answer_matches`.** As above.

Untouched: the row lock, the cap count, expiry, the orphan reconciler,
`authorise` (ownership was never challenge-scoped), and teardown on disband and
on event end.

`challenge_instance.challenge_id` stays, and keeps pointing at the challenge the
instance was **launched from** — the truthful record of where it came from, and
what the admin list shows. It stops being what lookups match on, which is the
change.

## Winding down after the last solve

When a solve lands on a challenge whose template is shared, and the owner has now
solved **every published challenge on that template**, the instance's
`expires_at` is set to `now + INSTANCE_COMPLETION_GRACE_SECONDS` (default 300)
if that is sooner than its current expiry.

Deliberately not an immediate teardown: the expiry reconciler already runs every
30 seconds and already tears down correctly, so this needs no second destruction
path, and five minutes means the container does not vanish out from under a
teammate who is still reading the thing they just solved. It only ever shortens a
TTL, never extends one, and a player who wants longer can still press extend.

## What the player sees

`InstanceResponse` gains `shared_challenge_count` — how many **other published**
challenges the same template serves. Zero for every unshared template, so nothing
that exists today changes appearance. Only published challenges are counted, so
it never reveals a draft.

- **Running, shared:** "This target also serves 3 other encounters in this area."
- **Running, dynamic flags:** the flags here are yours; a flag from another party
  will not be accepted. Said plainly and once, because the alternative is a
  support queue of teams who "found the flag" and got marked wrong.
- **Destroying, shared:** the confirm copy says shutting it down ends it for
  those encounters too. Tearing down the apothecary from the SQLi challenge must
  not quietly kill the traversal challenge a teammate is mid-payload on.

One correctness fix travels with it: `InstancePanel` keys its query on
`["instance", challengeId]` and invalidates only that key, so with a shared
target a destroy from one challenge leaves a stale cache entry under its
siblings. Launch and destroy invalidate the `["instance"]` prefix instead.

The admin instance list gains a **template** column, so staff looking at one pod
owned by a team that has solved three challenges can see why that is right.

## The admin template form cannot currently set the fields this needs

Found while specifying this, and it blocks 045's setup rather than merely being
untidy: `CreateTemplateRequest` accepts `ttl_seconds` and `injects_answer`, but
the form in `AdminInstancesPage.tsx` offers only **name, image, tag and port**.
Everything else takes its default, so an operator cannot create the
`web-apothecary` template as 045 specifies it.

This spec adds `ttl_seconds`, `injects_answer` and `shared_instance` to the form,
and shows all three in the template list, so an operator can see at a glance that
`web-apothecary` is shared, per-team-flagged and on a two-hour TTL.

## API surface

No new endpoints.

| Path | Change |
| --- | --- |
| `POST /api/challenges/{id}/instance` | returns the owner's existing instance for a shared template rather than launching a second; mints a flag for every published sibling |
| `GET /api/challenges/{id}/instance` | finds an instance launched from a sibling on the same shared template |
| `DELETE`, `.../extend` | act on that same shared instance |
| all of the above | response carries `shared_challenge_count` |
| `POST /api/challenges/{id}/submit` | a dynamic flag is checked against this team's row for this challenge |
| `POST /api/admin/.../templates` | accepts `shared_instance`; form exposes `ttl_seconds` and `injects_answer` |

## Testing

Against the fake orchestrator, deterministic, no cluster:

**Sharing**

- Four challenges on one shared template: launching from each yields **one**
  instance row and one set of cluster objects.
- That team's cap usage is one, so a second, different container still launches.
- `GET` on challenge B returns the instance launched from A; `DELETE` from B
  destroys it; `extend` from B extends it.
- Two challenges on an **unshared** template still get two instances — the
  regression test that this changed nothing by default.

**Flags**

- Launch mints one row per published sibling, and **no two of them share a tail**.
  This is the test that catches the collapse described above.
- Each flag is `flag{<stem>_<8 hex>}` for that challenge's own stem.
- A team's flag solves that team's challenge; **another team's flag for the same
  challenge does not**; nor does the correct flag for a *sibling* challenge.
- A submission with no live instance is wrong, not an error.
- Casefolded input still matches.
- An unpublished sibling gets no flag.
- A `dynamic` rule alone never matches through the pure resolver registry — the
  instance path is the only route to a solve.
- Saving a `dynamic` rule on a challenge with no container template is refused;
  so is a stem outside `[a-z0-9_]{1,64}`.

**Delivery**

- `INSTANCE_ANSWERS` is present on the pod spec, is valid JSON, is keyed by slug,
  and carries exactly the minted values.
- `INSTANCE_ANSWER` is set for a single-challenge template and absent for a
  multi-challenge one.

**Lifecycle**

- Solving the last published challenge on a shared template shortens `expires_at`
  to the grace window; solving the third of four does not; an instance already
  expiring sooner is not extended by it.
- Expiry and the orphan loop treat a shared instance as any other.
- Another owner cannot `GET`, `DELETE` or `authorise` it — sharing is between
  challenges, never between teams.

**Frontend**

- The shared notice, the per-team-flag notice and the destroy warning appear at
  `shared_challenge_count > 0` and none of them at zero.

## Commit plan

1. Migration: `challenge_instance_answer`, drop `generated_answer`,
   `shared_instance`; models.
2. `MatchType.DYNAMIC`, its resolver, its save-time validation, and CSV
   round-trip.
3. Minting at launch, `INSTANCE_ANSWERS` delivery, and the shared lookups in the
   launcher.
4. `answer_matches` against the new table, and the completion grace window.
5. `shared_challenge_count`, admin template form fields, admin template column.
6. `InstancePanel` notices, destroy warning, cache-key fix.

## Open questions

1. **Eight hex characters for the tail.** Long enough that nobody guesses it,
   short enough to retype. Confirm, or say longer.
2. **Five-minute completion grace.** Confirm, or set it to zero for an immediate
   wind-down.
3. **Should staff see a team's minted flags?** The admin instance drill-down
   could show them, which makes "it says my flag is wrong" answerable in ten
   seconds during the event. It also puts every live flag on a screen that gets
   shoulder-surfed. Recommendation: show them, staff-only and audit-logged, on
   the grounds that an unanswerable support question during a timed event is the
   worse failure. Not built unless you agree.

## Non-goals

- Sharing an instance **between owners** — one team, one target, unchanged.
- Per-challenge TTLs or resources on a shared template. One container, one
  lifetime.
- Minting a flag for a challenge published after launch. Relaunch covers it.
- Any change to the isolation controls in 008/009. Nothing here touches the pod.
