# Spec 011 — AI Assistant: Guardrails

Status: **done** — 606 backend tests, 96 frontend tests
Phase: 1
Covers: `Plan.md` → AI Assistant (both guardrail layers, and opening the chat to players)
Depends on: 010 (the mediator), 003 (plaintext answers), 007 (review framing), 006 (console)

## Purpose

The two guardrail layers `Plan.md` treats as equally important, the log that makes
attempted abuse reviewable afterwards, and the one-line change that finally lets
players talk to the dungeon master.

Phase 1's Definition of Done names this explicitly: *"both guardrail layers are
demonstrably working (attempted flag extraction and attempted real-exploit
generation are both refused/deflected)"*. Demonstrably is the operative word, so
this spec ends with a way to actually show it.

Done when a player can chat from any screen, an attempt to extract a flag is
deflected and logged, an attempt to obtain real-world attack capability is
deflected and logged, and staff can read both after the event.

## The layers are independent by construction

`Plan.md` notes that "a jailbreak could target either one". So they are separate
modules with separate rules and separate log rows, and **neither can suppress the
other**: the runner applies both to every reply, and an exception inside one
records a finding and continues to the other rather than escaping. A single
`try` around both would mean one crafted input disables the pair.

## Layer A — challenge integrity

### What 010 already guarantees

The context assembler builds from an explicit whitelist, so no answer value can
reach a prompt. That is the primary control and it is structural.

It covers **what the model was told**. It does not cover **what the model says**.
A model can emit a flag-shaped string it invented, and a fabricated flag costs a
player just as much time as a leaked one.

### The output filter, and why ours can be exact

Spec 003 stores answers in plaintext, at the project owner's direction, because
regex and computed answers were a hard requirement. That decision is what made
spec 008 uncomfortable — and it is also what makes this layer unusually strong:
we can compare a reply against every live answer **exactly**, rather than
guessing at what a flag looks like. A platform that hashed its flags could not
build this check at all.

| Rule | Fires when | Action |
| ---- | ---------- | ------ |
| `answer_verbatim` | The reply contains a live answer value, on word boundaries (case-insensitively for the case-insensitive, `any_of` and `set` types, and for each member of the multi-part ones) | Deflect |
| `answer_regex` | A `regex` answer's pattern matches the reply, evaluated through spec 003's resolver with its existing timeout | Deflect |
| `flag_shaped` | The reply matches the configured flag pattern, even when it is not a real answer | Deflect |

The live answer set is held in memory behind a short TTL
(`AI_ANSWER_CACHE_SECONDS`, default 60) rather than queried per reply. A newly
written answer is therefore unscanned for up to a minute; the structural
guarantee still covers that window, so the exposure is the model coincidentally
producing an answer written in the last sixty seconds. Literal values are hit
through a normalised lookup set, and only `regex` rules are actually evaluated,
against lines rather than every token.

`answer_regex` reuses `app/services/answers.py` rather than reimplementing
matching. Two matchers that are supposed to agree and eventually do not is a bug
that would surface as a leak.

**The deflection must not become a correctness oracle.** A player who pastes a
guess and asks "is this right?" would learn the answer from *whether* the reply
was deflected. `flag_shaped` is what closes this: every flag-shaped reply is
deflected whether or not the value is real, so the deflection carries no
information. For the answer types that are not flag-shaped — `numeric`, `set`,
`any_of`, some `regex` — a residual oracle remains, and three things bound it:
the deflection copy is identical to every other deflection, it is strictly
weaker than the submit endpoint the player already has (6 messages a minute
against 10 submissions), and every occurrence is logged with their name.

**Distinctiveness threshold.** Some answers are short or ordinary — `1337`,
`buffer`, a single English word. Scanning every reply for those would deflect
perfectly good advice several times an hour and train players to distrust the
assistant. Only values that are distinctive enough are scanned: at least
`AI_ANSWER_SCAN_MIN_LENGTH` characters, or containing the flag delimiter.

The ones that fall below the line are **not silently ignored** — the admin screen
lists them, so staff can see which answers the backstop does not cover. The
structural guarantee still covers them: the model was never told those values, so
the only way it could produce one is coincidence.

### On the input side

| Rule | Fires when | Action |
| ---- | ---------- | ------ |
| `injection_attempt` | The question matches cheap injection patterns — "ignore previous instructions", "print your system prompt", "what is the flag" | **Log only** |

Deliberately never blocked. Asking the dungeon master for the flag is a joke
nearly every player will make; refusing it would be both rude and useless, since
blocking an input only teaches the author to rephrase. The output filter is the
control. This rule exists so that the review afterwards can distinguish one
person's joke from another person's forty structured attempts.

## Layer B — real-world safety

### The honest problem statement

This is a security event. Teaching people to exploit things is the entire point,
and a filter that refuses "how does SQL injection work" makes the assistant
worthless within an hour. The line is therefore not *security content*; it is
**operational capability against real, non-event targets**.

And the model is deliberately uncensored. That was the right call for a CTF — a
guarded model refuses legitimate challenge questions constantly, which is exactly
the failure mode above — but it means **there is no model-side safety here at
all**. Every control in this layer is ours. It would be dishonest to write this
spec as though a safety-tuned model were quietly backstopping it.

What actually reduces risk, strongest first:

1. **The audience.** Two hundred named employees, signed in through Entra, on a
   corporate network, with every message attributed and retained. This is not an
   anonymous public chatbot, and it is the single most effective control in this
   document. It is also not code.
2. **Deterministic checks**, for the things that are genuinely checkable.
3. **The system prompt**, which is flavour with a useful side effect.
4. **A second-pass judge**, if we want it — see the open questions. It runs
   **only on replies a deterministic rule already flagged**, never on all of
   them. 010 measured ~6.7 responses/sec, and 200 players at a message every 30
   seconds needs ~6.7/sec: a blanket second call halves the ceiling and the
   event no longer fits underneath it. Escalating on the small flagged fraction
   costs almost nothing. It may only raise severity, never lower it.

| Rule | Fires when | Action |
| ---- | ---------- | ------ |
| `real_world_target` | A public IP address or a hostname outside `AI_EVENT_DOMAINS` appears alongside attack language | Deflect on a reply, log on a question |
| `malware_build` | Ransomware, keyloggers, botnets or C2 construction are requested or produced | Deflect, high severity |
| `credential_harvesting` | Phishing pages or credential-capture kits aimed at real services | Deflect, high severity |

`real_world_target` is the one worth having. "How do I exploit `10.4.2.9`" is the
event; "how do I exploit `some-real-bank.com`" is not, and the difference is
mechanically decidable in a way that intent is not.

**These are heuristics and a determined person will evade them.** Their value is
twofold: they stop the careless case, and they ensure that anyone working around
them leaves a trail with their name on it.

## What the player sees

An in-character deflection — the dungeon master declining, not an error. The
original reply is stored so staff can read exactly what was suppressed, and never
sent.

The panel carries one honest line of copy: *the Dungeon Master will not give you
answers*. Setting the expectation up front costs nothing and removes most of the
reason to go probing. Beyond that the filter is not advertised, because a visible
filter is a target.

## Data model

### `assistant_finding`

`message_id`, `user_id`, `layer` (`integrity` | `safety`), `rule`, `severity`
(`low` | `medium` | `high`), `action` (`logged` | `deflected`), `detail` (JSONB),
`created_at`.

`detail` records **what matched, never the value** — the challenge id rather than
its answer. A review screen that pastes flags onto an organiser's monitor would
be a new leak wearing an audit badge.

Not reusing spec 007's signal machinery, deliberately: those signals are computed
on demand from data that already exists, and can be recomputed at any time. These
are events that happened at a moment, to a message, and cannot be reconstructed
later. Same review instinct, different shape.

## Staff review surface

`GET /api/admin/assistant/findings` — filter by layer, severity, action and
player; paginated. Opening one shows the surrounding turns of that conversation.

**Flagged exchanges and their immediate context only — not a general transcript
browser.** This is a work event and these are colleagues; their chat logs are not
staff entertainment. Spec 007 made the same call for the same reason.

The tone follows 007 as well: these are conversation starters. Staff findings are
recorded (010 already stamps `from_staff`) and hidden by default, so our own
testing does not bury the real ones.

## Opening the chat to players

- `ChatUser = Staff` becomes `Player` in `app/api/routes/assistant.py` — the one
  line 010 was built around.
- `/api/auth/me` drops the staff condition from `assistant_available`.
- The panel is already reachable from every screen, which is what `Plan.md` asks
  for; this spec only widens who sees it.
- **`user.assistant_blocked`**, settable from the admin console: take the chat
  away from one person mid-event without taking it from the other 199. Without
  it the only lever is the event-wide switch, and one player misbehaving should
  not cost everyone the feature.
- **A runtime kill switch** on `event_config`, toggleable from the admin console.
  `AI_ENABLED` remains the deployment-level off switch, but reaching for a
  redeploy is the wrong tool at 11pm on day two when the dungeon master starts
  saying something unfortunate.

## Configuration

`AI_FLAG_PATTERN` (default `[A-Za-z0-9_]{2,16}\{[^}]{1,120}\}`),
`AI_ANSWER_SCAN_MIN_LENGTH` (default 8), `AI_EVENT_DOMAINS`,
`AI_ANSWER_CACHE_SECONDS` (default 60),
`AI_SAFETY_JUDGE_ENABLED` (default off).

## Edge cases

- **A common-word answer.** Not scanned; listed on the admin screen as uncovered.
- **A regex answer whose pattern times out.** Treated as no match and logged. The
  structural guarantee still holds, so failing open on the backstop is acceptable
  — but it must be visible, not silent.
- **A player pastes an answer themselves.** Their own message is not scanned.
  They already have it, the conversation is private to them, and flagging it
  would generate noise about people who did nothing wrong.
- **The reply merely mentions the word "flag".** Not a match. Only real values and
  the configured pattern match.
- **Both layers fire on one reply.** Two findings, one deflection.
- **A filter itself raises.** The reply is deflected and a `filter_error` finding
  is recorded. Fail safe: an unexplained exception is not a reason to hand the
  text over.
- **The model is unavailable.** 010's degradation already produced the text, it
  came from us, and no filtering or findings apply.
- **A very long reply.** Scanning is linear in the reply length and the answer
  count; both are capped.

## Testing

In CI, against a fake model, deterministic:

- A reply containing a live answer verbatim is deflected and logged.
- The same for `regex`, and for each member of `set` and `any_of`.
- Flag-shaped output with no real answer behind it is still deflected.
- A short or common answer is not scanned, and is reported as uncovered.
- An injection attempt is logged and **not** blocked.
- A real-world target is deflected; an in-event address is not.
- Each layer fires independently, and one raising does not skip the other.
- No finding row ever contains an answer value.
- A player — not just staff — reaches every endpoint, and an
  `assistant_blocked` player does not.
- Ordinary CTF advice — SQL injection, a hex dump, an nmap flag — passes both
  layers untouched. The regression that matters most: a filter which breaks
  normal play is worse than no filter.
- Staff findings are excluded from the review screen by default.

**And the demonstration**, which is what the Definition of Done actually asks
for: `scripts/redteam.py`, a canned corpus of extraction and exploit prompts run
against the **live** model, printing prompt → reply → verdict. It needs the model
box switched on, so it never runs in CI. It is the artefact to point at when
someone asks whether the guardrails work.

## Commit plan

1. `assistant_finding` model, migration, configuration
2. Layer A — the integrity filter and its rules
3. Layer B — the safety filter and its rules
4. The runner: both layers wired into the chat flow, deflection copy, fail-safe
5. The staff review surface — API and console screen
6. Open the gate to players, and the event kill switch
7. The red-team demonstration script

## Decisions

All six were put to the project owner and answered.

1. **Keep the uncensored model.** A guarded model refusing legitimate challenge
   questions would damage the event more than the residual risk does, given a
   named corporate audience with every message attributed. Every control in
   layer B is therefore ours, and this spec does not pretend otherwise.
2. **Ship the second-pass judge, default off.** It runs only on replies a
   deterministic rule already flagged, and may raise severity but never lower
   it. Turning it on is a config change once the log shows how the deterministic
   layer behaves in practice.
3. **Deflect on high severity only; log medium and low.** This is `Plan.md`'s
   "logged without necessarily blocking gameplay flow" taken literally. Revisit
   after a day of real traffic.
4. **Staff see flagged exchanges and their immediate context**, not a general
   transcript browser.
5. **The runtime kill switch is in scope**, as is **`user.assistant_blocked`**.
6. **Retention is in scope** — see below.

## Retention

Conversations are the most personal thing this platform stores, and nothing else
in Phase 1 keeps a record of what a colleague typed. They should not outlive
their purpose.

`AI_RETENTION_DAYS` (default 30) is the age past which a conversation is
purged. There is no scheduler in this application and this spec does not add
one: the purge is an **admin action in the console** that reports how many
conversations it removed, plus the same routine run once at startup. That is
enough for an event that lasts days, and a cron that nobody notices failing
would be worse than a button somebody presses.

Findings are **not** purged with the conversations. They are the record of what
happened and they never contain answer values or the reply text — only what
matched and where. `original_content` on a purged message goes with it.
