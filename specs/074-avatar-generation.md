# Spec 074 — Avatar Generation

Status: **draft**
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
  the inbox (028/065) so nobody has to sit on the page.
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

## 9. Open questions

1. **Can a player portray a class that is not theirs?** Recommend **any class
   they have unlocked**, defaulting to their current one — it rewards
   progression without freezing a choice they are encouraged to revisit.
2. **48 class fragments is real authoring work.** Recommend writing all 48
   anyway, with an archetype fallback for any left blank, because the class
   fragment is the axis doing the most work.
3. **Starting budget of three, and does a reroll of the same traits cost one?**
   Recommend **three**, and **yes** — otherwise the grid is a slot machine.
4. **Does the operator want candidates kept after a pick?** Recommend a short
   TTL and no gallery. Storing every rejected portrait of every player for five
   days buys nothing.
