# Spec 055 — Email Delivery Log

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement), 052 (the player detail panel this surfaces in)

Persist every outbound email attempt and show it, so "the guest never got their
link" becomes an answerable question.

## 1. The problem, precisely

[`mail.py`](../backend/app/services/mail.py) is written correctly for its
constraints. `send_magic_link` never raises, because the caller must answer 202
either way — otherwise a failing relay becomes a way to probe which addresses
exist. It returns a boolean and logs:

```python
logger.error("magic_link_send_failed", extra={"error_type": type(exc).__name__})
```

Its own module docstring says the point of that log is so that "an admin can find
it mid-event rather than guessing why one player never got their link."

**The admin cannot find it.** The log goes to the pod's stdout. Reading it means
`kubectl logs` against a cluster owned by a different session, at the moment a
guest is standing in front of you unable to sign in. And the log deliberately
records only the exception *type*, never the recipient — correct for a log, and
it means even with cluster access you cannot tell which address failed.

So the one signal that exists is both unreachable and, by design, insufficient.

Three ways this bites during the event, in descending likelihood:

1. **A guest never got their magic link.** Was it sent? Did the relay reject it?
   Is it in their spam? Right now: unanswerable, and the fallback is asking them
   to try again and hoping.
2. **SMTP is misconfigured or the token has expired.** Every guest login is
   failing silently, and the first signal is people complaining. `MailNotConfigured`
   is raised and swallowed.
3. **An approval notice never arrived**, so someone approved the night before has
   no idea they can now play.

## 2. The model

A new `email_delivery` table. One row per attempt.

| Column | Notes |
| --- | --- |
| `id`, `created_at` | |
| `kind` | `magic_link` / `approval_notice`. An enum, so a third kind later is a migration and not a free-text mess. |
| `to_email` | The recipient. See §5 on why storing it is acceptable. |
| `user_id` | Nullable — a magic link can be requested for an address with no account. |
| `status` | `sent` / `failed` / `not_configured`. |
| `error_type` | The exception class name, as the log already records. Never the message — see §5. |
| `duration_ms` | How long the relay took. A relay that is slow rather than broken looks like nothing else. |
| `request_id` | Ties back to the application logs. |

**`status` means "the relay accepted it", not "it arrived."** SMTP gives no
delivery confirmation, and a row saying `sent` for something that bounced later
would be a lie the page tells confidently. The UI says *accepted by relay*, which
is the true thing.

## 3. Writing rows without changing the security properties

The recording happens **inside `send_message`'s callers in `mail.py`**, not at the
route, so every path gets it and nobody has to remember.

Two properties that must not regress:

- **`send_magic_link` still never raises**, and the caller still answers 202
  regardless. Writing a delivery row must not become a way to make the endpoint
  behave differently for a known address versus an unknown one. The row is
  written on both paths, identically.
- **The write must not block the response.** Sending is already best-effort and
  off the response path; the row is written in the same background context, and a
  failure to write the row is logged and swallowed. An audit-adjacent record is
  not worth failing a login over.

## 4. The page — `/admin/email`

Under Settings, because it is mostly a "is the mail path working" surface and
that is a setup question.

**A status band at the top**, which is the part that earns the page:

- Is SMTP configured at all — `settings.smtp_configured`, reported plainly.
- Sends in the last hour, and the failure rate among them.
- **A prominent failure banner when the recent failure rate is high**, because
  "every guest login is broken" is the failure mode nobody notices until it has
  been true for an hour.
- **Send a test email** — to the admin's own address, showing the result inline.
  The one control that turns "is mail working?" from a guess into a fact, and the
  first thing anyone will reach for.

**A table below**: time, kind, recipient, status, error type, duration. Filters
for kind, status and a date range; search by recipient address.

**In the player detail panel** (spec 052), the same rows filtered to that person,
right beside the resend-magic-link action. That is where this is used most:
someone is stuck, you open their record, and you can see the three links that
were sent and that all three were accepted — so it is their spam folder, and you
can tell them so.

## 5. Storing recipient addresses

The table stores `to_email` in plaintext, which is a deliberate departure from
how the logs treat it, so the reasoning belongs here:

- The `user` table already stores every one of these addresses as the identity
  key. This introduces no category of data the database does not already hold.
- The address is **the entire diagnostic value**. A delivery log you cannot search
  by recipient answers none of the three questions in §1.
- The distinction being preserved is **logs versus database**: application logs
  are shipped, aggregated and read broadly, so they stay free of addresses. The
  database is already the system of record for them.

What is *not* stored: the message body, the magic-link token or URL, and the
exception message (which `mail.py` notes can contain the recipient address — the
type only, as it already does). A delivery log holding a live login link would be
a credential store.

## 6. Retention

Rows are kept for the event and are covered by the play-data reset groups in spec
043 as their own group, so a reset between a rehearsal and the real event clears
them. No automatic expiry: five days of an event this size is a few thousand rows.

## 7. API

- `GET /api/admin/email/deliveries` — filters for kind, status, date range,
  `search` by recipient, `user_id`; paginated with a `total`. `Staff`.
- `GET /api/admin/email/status` — configured, recent counts, failure rate.
  `Staff`.
- `POST /api/admin/email/test` — sends a test message to the calling admin's own
  address. **`Admin`**, rate-limited, and it writes a delivery row like any other
  send. Deliberately cannot take an arbitrary recipient: an authenticated
  send-to-anyone endpoint is an open relay with extra steps.

## 8. Testing

- A successful send writes a row with `status = sent` and a duration.
- A relay failure writes `status = failed` with the exception type and no message.
- Unconfigured SMTP writes `status = not_configured`.
- **A magic-link request for an unknown address writes a row and still returns
  202**, indistinguishable from a known address — the existing enumeration test
  extended to cover the new write.
- A failure to write the delivery row does not fail or alter the send.
- **No row ever contains a token, a link, or an exception message** — its own
  test, checked across all three statuses.
- The status band's failure rate matches the underlying rows.
- The test-send endpoint refuses a supplied recipient and always uses the caller's
  address.
- The test-send endpoint is rate-limited.
- Delivery rows appear in the player detail panel filtered to that user, including
  rows written before that user had an account (matched on address).
- A play-data reset of the email group clears the table and nothing else.

## 9. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. ~~**Should a high failure rate raise a notification?**~~ **Decision
   (2026-09-17): no.** Delivery has been reliable, and the mail provider already
   emails the admin directly when sends start failing — an in-app notification
   would be a second alarm for a bell that already rings, built on a threshold
   nobody has a baseline for. The §4 status band and failure banner stay; they are
   read when you go looking, which is the point. **Phase 3 ships no alerting
   anywhere.**
2. **Is `Staff` the right level for reading the log?** It contains every guest's
   email address. With one admin the question is academic, but the principle
   (spec 052 keeps roles unextended) suggests reads stay `Staff` and only the
   test-send is `Admin`. Recommend as written; flagging because it is the one
   admin surface holding a list of personal addresses.
