# Spec 074 — Avatar Generation

Status: **done**, amended by §11
Phase: 3 (Polish & Operability) — feature
Depends on: 073 (the renderer, storage and accessory layers), 010 (the model-client pattern)
Second of two: 073 the parts that need no GPU, **074** this.

A local SDXL Turbo service on the operator's own host turns a set of chosen
traits into a portrait. Every trait is an enum. **No player ever writes a
prompt.**

## 1. Why enums are the whole design

Not letting players type is the single largest decision in this spec, and it
pays three times over:

- **Safety.** No free text means no NSFW prompt, no slurs, and no prompt
  injection — not mitigated, *absent*. This matters more than usual here:
  SDXL Turbo runs at `guidance_scale=0.0`, which means **negative prompts are
  ignored**, so the usual "add a negative prompt" control is not available. The
  filter has to be the input vocabulary.
- **Quality.** Eight authored fragments tuned once beat 200 people's first
  attempt at prompt engineering.
- **Identity.** The traits are the game's own vocabulary — the 48-class roster
  (024), ancestries, the loot palettes — so a portrait looks like it came from
  this event rather than from a generic model.

The client sends **trait keys only**. The server assembles the prompt. A request
carrying prompt text is rejected, and that is a test, not a convention.

## 2. The builder

Eight axes, each an authored enum, seeded into the DB from a module in the repo
so they can be tuned during setup the way the class roster can:

| Axis | Roughly | Notes |
| --- | --- | --- |
| `ancestry` | 14 | human, elf, dwarf, orc, tiefling, goliath… |
| `class_look` | 48 | one fragment per real class |
| `garb` | 10 | robes, plate, leather, rags, finery… |
| `headwear` | 10 | hood, helm, circlet, bare… |
| `expression` | 8 | stoic, grim, weary, fierce, amused… |
| `palette` | 10 | drawn from the theme-invariant ladders |
| `setting` | 10 | dungeon, forest, tavern, arcane, void… |
| `art_style` | 8 | oil, ink, woodcut, illuminated manuscript… |

```
AvatarTrait: axis, key, label, prompt_fragment, sort_order, enabled
```

`prompt_fragment` is **never sent to the client**. The builder shows labels; the
prompt-engineering stays server-side. A "Surprise me" button randomises every
axis, which is the fastest route to a good portrait for anyone who does not want
to make eight decisions.

`class_look` defaults to the player's **actual class** — that is what ties the
portrait to progression rather than to a costume box.

## 3. Style, deliberately

Prompts steer hard toward **painted portrait**, not photography. Turbo at 512 is
weak at photoreal faces and good at stylised work, so this is designing with the
model's grain instead of against it. A painted portrait also sidesteps the
uncanny-valley failure that made work-photo transformation a bad idea.

## 4. The client, and the host

`app/services/image_client.py` is a deliberate twin of `ai_client.py`, whose
docstring already makes the argument: the host *"lives outside the cluster, on a
box whose uptime we do not control, and it will be unreachable at some point
during a multi-day event."* Same shape — failure as a return value, a circuit
breaker, coarse reasons (`disabled`, `unconfigured`, `timeout`, `unreachable`,
`bad_response`, `breaker_open`, `busy`).

Settings mirror the `ai_*` block: `image_base_url`, `image_api_key`,
`image_enabled`, `image_model`, `image_timeout_seconds`, `image_max_concurrency`,
`image_breaker_threshold`, `image_breaker_cooldown_seconds`.

**The host address never enters the repo.** Config and environment only, per
`CLAUDE.md`.

### The service itself

A small reference service under `tools/avatar-service/` — FastAPI + diffusers,
`POST /generate` taking a prompt, seed and step count and returning a PNG, plus
`GET /health`. It is **not** deployed to the cluster and has its own README for
setup on a Windows host with a GPU. SDXL Turbo needs roughly 8GB of VRAM at
fp16; the README notes Flux Schnell as the swap for a bigger card, since the
contract is just prompt-in, PNG-out.

It runs the NSFW classifier, because that is where the GPU already is.

## 5. Generating, as a queue

One GPU and 200 players means a request is not a request, it is a **job**.

- A job generates **four candidates** at different seeds, shown as a grid to
  pick from. One generation that has to be right is worse than four and a
  choice, and the marginal cost on Turbo is small.
- Jobs queue with a visible place in line, and the finished grid arrives through
  the inbox (028/065) so nobody has to sit on the page. **Not built** — see
  §10. The request runs the generation inline and the player waits on the page.
  Carried forward in `plan.md`.
- **Budget:** three generations to start, and more as a loot drop. This caps the
  reroll spiral and feeds the existing economy rather than bolting a limit on.
- Candidates live in object storage (the `ArtifactStorage` abstraction from 063)
  with a TTL. Only the chosen one is composited into `avatar_blob`.

## 6. Safety

- Enum keys only, assembled server-side (§1).
- NSFW classifier on the output, at the service (§4).
- Every job logs the user and the trait keys, so a bad portrait is traceable to
  the exact inputs that produced it and the offending fragment can be disabled.
- Admin reset, built in 073 §8.

## 7. When the host is dark

`image_enabled=false`, an unconfigured host or an open breaker all produce the
same thing: **the generation entry point is not offered.** Sigils, Entra photos,
accessories and the editor are untouched, because 073 needs no GPU. A player who
already has a generated portrait keeps it — the bytes are in `avatar_blob`, and
nothing re-renders against the model.

## 8. Testing

- Trait keys assemble into the expected prompt; an unknown key is rejected.
- `prompt_fragment` never appears in any response body.
- A request carrying free-text prompt content is rejected.
- Budget: the fourth generation is refused; a loot grant restores one.
- Queue: jobs run to the configured concurrency and no further.
- Every `image_client` failure mode returns rather than raises, and the breaker
  opens and cools down — mirroring the existing `ai_client` tests.
- With `image_enabled=false` the builder is absent and the rest of the avatar
  system is unaffected.
- No test calls the real host; the client is faked the way the AI client's are.

## 9. Decisions

1. **Any class, defaulting to your own.** The builder pre-selects the player's
   real class and the axis is otherwise open — unlock-gating it would have meant
   a second unlock system for a costume, and the default already does the work
   of tying a portrait to progression.
2. **All 48 fragments written**, and the archetype fallback turned out to be
   unnecessary — see §10.
3. **Three, and yes**, a reroll costs one. Loot grants more, so the reroll
   spiral gets a tap rather than a wall.
4. **A 24-hour TTL and no gallery.** Picking one deletes the rest of its grid
   immediately; `purge_expired` sweeps anything nobody chose.

## 10. What the build changed

- **The archetype fallback was a bad idea and is not there.** Writing it would
  have hidden the actual bug: the first pass shortened the four mythic class
  names and omitted four classes outright, so **eight of the 48** would have
  silently fallen through the "default to your class" lookup — and a fallback
  would have made that invisible rather than loud. `class_look` labels now match
  migration 0027 exactly, and a test asserts the two sets are equal in both
  directions.
- **A safety refusal must not open the circuit breaker.** A 422 from the service
  is a *working* host saying no to one combination. Treating it as a failure
  would let one unlucky set of traits take generation down for everybody for two
  minutes.
- **A failed job does not spend the budget.** Charging a player for our own
  downtime would be an unpleasant surprise, so `generations_used` counts only
  jobs that reached the model.
- **A dark host stops after one attempt, not four.** There is no point asking a
  switched-off box three more times.
- **Jobs run inline**, not through a worker, which drops two things §5 promised
  and the first note did not own: there is **no visible place in line** and
  **no inbox delivery**. The player waits on the page, and a second player
  generating at the same time gets `busy` — which the builder currently reports
  as "that did not come out, try different choices", blaming their choices for
  contention. Adequate for a few people trying it; wrong for 200 on the first
  morning. Carried forward in `plan.md` under "Carried forward, not built".
- **Candidate bytes live in Postgres, not object storage.** They are small,
  short-lived, and always fetched one at a time by the one player who owns them;
  a bucket round trip would have been the slow part of showing the grid.
- **`StartJobRequest` has no field for prose**, asserted directly rather than
  inferred from the endpoint — the endpoint test would pass whatever the schema
  did, since no host is configured in CI.
- **Counts:** 8 axes, 118 authored options, 37 backend tests, 12 frontend tests.

---

## 11. Amendment — the vocabulary, the grid, and the budget

From using it. Three things were wrong and one was missing.

### 11.1 The grid has to stay put

Choosing a candidate **deleted the other three** and cleared the grid, so a
second thought was impossible: the portrait you preferred was already gone. That
was written as a storage saving and it is not worth the cost.

- All candidates from the most recent job **stay** until the next job replaces
  them. Choosing is now reversible as many times as you like.
- The job records `chosen_candidate_id`, so the grid can mark which one is live
  and survive a reload knowing it.
- Generating again clears the previous job's candidates — one grid at a time,
  which is what "until more images are generated" means.

### 11.2 The seven axes

Headwear and Background are retired; Clothing covers the first and the house
style covers the second. **Presentation** is added. The authored lists are
replaced wholesale, so seeding must now *retire* options that are no longer
authored rather than leaving them alongside the new ones.

| Axis | Options |
| --- | --- |
| Ancestry | Human, Elf, Dwarf, Halfling, Orc, Tiefling, Dragonborn, Gnome, Celestial, Fiendish |
| Class | **The player's own unlocked classes**, and only at level 5 or above |
| Clothing | Heavy Plate Mail, Leather Scouting Gear, Flowing Sorcerer Robes, Elegant Noble Attire, Tattered Rogue Hoods |
| Colours | Warm, Cool, Earthy, Shadow, Radiant |
| Expression | Determined, Confident, Serene, Fierce, Weary, Amused, Watchful |
| Presentation | Masculine-presenting, Feminine-presenting, Androgynous-presenting |
| Art Style | oil, ink, woodcut, illuminated, watercolour, charcoal, stained glass, storybook |

**Class is not a static list.** The fragments for all 48 stay in the table, but
the builder offers only what `available_classes()` returns for that player, and
nothing at all below `class_unlock_level` (5) — the same rule that already gates
choosing a class, reused rather than reinvented.

**Presentation is optional and stays optional.** "Any" is the default on every
axis and means the axis is simply left out of the prompt; on this one that is
the point, not an oversight. The three options describe *how a portrait looks*,
not who anybody is, which is why the wording is "-presenting" and why there is
no fourth "prefer not to say" — leaving it unset already is that.

### 11.3 The budget does not apply to admins

An admin testing the feature ran out, which is the wrong failure. Admins are
**exempt**, shown as unlimited rather than as a number. Separately, every player
gains a `portrait_grant` an admin can raise from the user page, so somebody who
lost four portraits to a bad afternoon can be topped up without a deploy.
