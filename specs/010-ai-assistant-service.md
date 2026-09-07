# Spec 010 — AI Assistant: Mediator Service

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → AI Assistant (the service, the model client, conversations)
Depends on: 002 (identity, the `play` gate), 003 (challenges), 004 (hints)
Followed by: spec 011, which adds both guardrail layers and opens it to players

## Purpose

A backend service that mediates every call to the locally-hosted model, and a
conversation a player can hold with it. The frontend never talks to the model;
this service is the only thing that knows where it lives, and the only place
guardrails can be enforced.

Done when a staff member can hold a conversation with the dungeon master from
any screen, the exchange is persisted and logged, and the model being unreachable
degrades the chat rather than the platform.

**This spec does not open the assistant to players.** The endpoints are
staff-gated until spec 011 lands the guardrails. That ordering is deliberate:
`Plan.md` treats both guardrail layers as first-class requirements, and shipping
an unguarded assistant to 200 people in the interim would be the wrong shape of
mistake.

## What we actually measured

I probed the running endpoint before designing against it, and three results
changed decisions:

| Measured | Result | What it changed |
| -------- | ------ | --------------- |
| Latency, short reply | **0.4 s** | No streaming. See below |
| 8 concurrent requests | **1.2 s wall clock, ~6.7 responses/sec** | Capacity is not the crisis I expected |
| Wrong API key | **Accepted** | LM Studio is not enforcing auth — see the security note |
| Reasoning output | Returned in a **separate `reasoning_content` field**, not inline `<think>` tags | Never forwarded; logged instead |

**No streaming, and that is a measurement rather than a shortcut.** At ~1 second
a plain request/response with a typing indicator is honest and far less
machinery than SSE plus the `proxy-buffering: off` it would need at the ingress.
If replies grow long enough to feel slow, streaming is an additive change to one
endpoint.

**Capacity is fine.** At ~6.7 responses/sec, 200 players each sending a message
every 30 seconds would need ~6.7/sec sustained — which is the measured ceiling,
so the limits below exist to keep us under it rather than to ration a scarce
resource.

## Security note: the model endpoint is unauthenticated

The endpoint accepted a deliberately wrong bearer token. The key that was
configured **does not gate anything** — anyone who can reach that host and port
on the LAN can use the model, at no cost to them and full cost to the box
running the event.

We will still send `AI_API_KEY`, because it costs nothing and starts working the
day LM Studio enforces it. But the real control is network-level and belongs to
whoever owns that host: restrict the port to the cluster node's address. Worth
raising, because "there is a key" reads like authentication and here it is not.

## Non-goals

- **Guardrails (011).** Both layers, the filtering, the abuse log and the player
  rollout live there.
- **Personality and lore.** `Plan.md` puts that in Phase 3. The system prompt
  here is competent and plain; it is scaffolding for a writer, not the writing.
- **Streaming, tools, function-calling, retrieval.** None are needed at 1 second.
- **Conversation search, export, or admin browsing.** 011 adds the review
  surface it needs for abuse; a general transcript browser is not Phase 1.

## The architectural guarantee

`Plan.md` requires that the assistant "must never be given the actual flag values
or answer-revealing content in its context/prompt", and that the system prompt
"must resist prompt-injection attempts".

**A system prompt is not a security boundary**, and on an 8B model it is a
particularly weak one. Players will get it to say things it was told not to.

So the guarantee is structural instead: **the context assembler builds its
payload from an explicit whitelist of fields, and answers are not on it.** There
is no code path that can place a `challenge_answer` row into a prompt. A fully
compromised system prompt therefore leaks nothing, because nothing is there.

What the model is told:

| Included | Why |
| -------- | --- |
| Player's display name and party name | Addressing them by name is most of the flavour |
| The challenge they are looking at: title, category, difficulty, points, body | Without this it cannot help at all |
| Hint bodies **they have already unlocked** | They paid for these; the assistant may reference them |
| Their own recent conversation turns | Continuity |

| Excluded, structurally | Why |
| --- | --- |
| `challenge_answer.value`, in any form | The whole point |
| Hint bodies they have **not** unlocked | Otherwise the assistant is a free hint bypass, undercutting spec 004 |
| Any other player's data, scores or submissions | Not theirs to know |
| Challenges they cannot see | Locked and hidden stay locked and hidden |

The assembler is a single function with a single test asserting that no answer
value appears in any prompt it can produce, for any challenge in the database.

## Conversation model

One rolling conversation per player, because `Plan.md` wants the chat "available
from any screen" — a per-challenge thread would mean losing the thread every time
they navigate.

Each message records which challenge the player was looking at, so the assistant
gets context without the player having to restate it, and so 011 can review what
was asked about what.

### `assistant_conversation`

`user_id` (unique), `message_count`, `last_message_at`.

### `assistant_message`

`conversation_id`, `sequence`, `role` (`user` | `assistant`), `content`,
`challenge_id` (nullable — what they were looking at), `model`,
`prompt_tokens`, `completion_tokens`, `latency_ms`, `reasoning_content`
(nullable), `error` (nullable), `created_at`.

`sequence` was **added during implementation**, and the deviation is worth
recording: `created_at` cannot order these rows. Postgres stamps `now()` at
transaction start, so a question and the answer it produced always carry an
identical timestamp and sorted arbitrarily — the history came back reversed
about half the time. It is unique per conversation.

**`reasoning_content` is stored and never returned.** The model exposes its
scratchpad in a separate field; it may contain the model reasoning aloud about a
challenge, and it is not for players. Keeping it makes 011's review job possible
and gives us something to look at when an answer is odd.

## History and prompt size

Only the last **10 turns** go back to the model, and the assembled prompt is
capped at a token budget. Longer conversations are truncated from the oldest end,
never the newest.

An 8B model's usable context is smaller than its advertised one, and a prompt
that grows unbounded across a multi-day event will eventually degrade the reply
quality before it errors — which is worse, because nobody notices.

## Limits

| Limit | Default | Reasoning |
| ----- | ------- | --------- |
| Messages per player per minute | 6 | A conversation, not a firehose |
| Messages per player per hour | 100 | Generous; catches a stuck loop |
| Global in-flight requests | 8 | Matches the measured concurrency sweet spot |
| `max_tokens` per reply | 400 | Keeps latency near the measured figures |
| Request timeout | 30 s | Far beyond the ~1 s measured; catches a wedged host |

Rate limiting **fails open** — unlike flag submission. If Redis is down, the
worst case here is someone talking to a chatbot more than intended; there, it was
the integrity of the scoreboard. Different stakes, different default.

## Degradation

The model runs on a box outside the cluster. It will be unavailable at some
point during a multi-day event, and **that must not take anything else down**.

- A failed call returns a friendly, in-character refusal and records the error on
  the message row.
- Repeated failures trip a **circuit breaker**: after 5 consecutive failures the
  service stops calling for 60 seconds and answers immediately from the breaker.
  A wedged host must not turn every player's chat into a 30-second wait.
- `AI_ENABLED=false` turns the whole feature off cleanly, and `/api/auth/me`
  reports it, so the UI hides the chat rather than offering a button that fails.
- Assistant health appears on the spec 006 dashboard beside the container panel.

## API surface

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/assistant/conversation` | **staff (011: play)** | Recent turns |
| POST | `/api/assistant/messages` | **staff (011: play)** | `{content, challenge_id?}` → the reply |
| DELETE | `/api/assistant/conversation` | **staff (011: play)** | Start again |
| GET | `/api/admin/assistant/health` | staff | Reachability, breaker state, recent latency |

The gate widens from `Staff` to `Player` in 011, in one place, once the
guardrails exist.

## Configuration

`AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_ENABLED`, `AI_TIMEOUT_SECONDS`,
`AI_MAX_TOKENS`, `AI_TEMPERATURE`, `AI_MAX_CONCURRENCY`, `AI_HISTORY_TURNS`.

`AI_BASE_URL` points at the platform session's in-cluster `ai` Service, so the
value never changes when the host address does. It stays a **secret** rather than
a manifest value: the project rules forbid the model's address in git, and the
repo is public.

## Edge cases

- **The model is unreachable.** In-character apology, error recorded, breaker
  counts it. No 500 reaches the player.
- **The model returns an empty reply.** Treated as a failure, not shown as an
  empty bubble.
- **The player asks with no challenge open.** Fine — general chat, no challenge
  context assembled.
- **The player asks about a challenge they cannot see.** The assembler resolves
  the challenge through the same visibility rules as spec 003, so a locked one
  contributes nothing.
- **A hint is unlocked mid-conversation.** The next turn includes it; earlier
  turns are not rewritten.
- **A very long message.** Capped at 2,000 characters before it reaches the model.
- **The model echoes its own system prompt.** Not a leak — the prompt contains no
  answers by construction. Untidy, and 011's output filter tidies it.
- **A disabled account.** Cannot reach any of this; the `play` gate already
  handles it.

## Testing

- The context assembler never emits an answer value, asserted against a database
  containing challenges with known answers.
- Locked hint bodies never appear in a prompt; unlocked ones do.
- A challenge the player cannot see contributes nothing.
- History truncates from the oldest end and respects the token budget.
- An unreachable model produces a friendly reply, not a 500.
- The circuit breaker opens after consecutive failures and closes again.
- `reasoning_content` is persisted and never present in any API response.
- Rate limiting fails **open** when Redis is unavailable.
- Every endpoint refuses a player while the gate is still `Staff`.

The model client is faked in tests. Nothing in CI should depend on a GPU box
being switched on.

## Commit plan

1. Migration: `assistant_conversation`, `assistant_message`; config
2. Model client: timeouts, concurrency limit, circuit breaker, health
3. Context assembler and system prompt, with the whitelist test
4. Chat endpoints, rate limiting, degradation
5. Frontend: the chat panel, staff-only for now

## Open questions

1. **Should the assistant know the player's score and solve count?** Harmless and
   good for flavour ("you have cleared four, brave one"). Proposed yes.
2. **Should staff conversations be visibly marked as staff?** They will be the
   only ones testing it before 011, and mixing their transcripts with players'
   later could confuse the abuse review. Proposed: record the role on the
   message row.
