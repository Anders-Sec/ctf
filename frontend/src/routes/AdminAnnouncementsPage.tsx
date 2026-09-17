import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelAnnouncement,
  createAnnouncement,
  listAnnouncements,
  type Announcement,
} from "../api/announcements";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Announcements (spec 054).
 *
 * The composer was right about everything except what happens after the send:
 * it reported a recipient count and then cleared itself. Over five days that
 * leaves no way to answer "what have I already told people?" without asking a
 * player to read their feed back to you.
 */
export default function AdminAnnouncementsPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audience, setAudience] = useState<"everyone" | "staff">("everyone");
  const [scheduledFor, setScheduledFor] = useState("");
  const [confirming, setConfirming] = useState(false);

  const history = useQuery({
    queryKey: ["admin", "announcements"],
    queryFn: () => listAnnouncements(),
  });

  const send = useMutation({
    mutationFn: () =>
      createAnnouncement({
        title: title.trim(),
        body: body.trim(),
        audience,
        scheduled_for: scheduledFor ? new Date(scheduledFor).toISOString() : null,
      }),
    onSuccess: async () => {
      setTitle("");
      setBody("");
      setScheduledFor("");
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["admin", "announcements"] });
    },
  });

  const cancel = useMutation({
    mutationFn: (id: string) => cancelAnnouncement(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "announcements"] }),
  });

  const ready = title.trim().length >= 3 && body.trim().length >= 3;
  const scheduling = scheduledFor !== "";

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Announcements</h1>
        <p className="mt-2 text-sm text-content-muted">
          Goes out in the System AI&rsquo;s voice and lands in every feed at once. It cannot be
          taken back — a correction is another announcement.
        </p>
      </header>

      <ErrorMessage error={history.error ?? send.error ?? cancel.error} />

      <section className="mt-6 rounded border border-border bg-surface-raised p-4">
        <label className="block text-sm">
          <span className="mb-1 block text-content-muted">Title</span>
          <input
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setConfirming(false);
            }}
            aria-label="Announcement title"
            className="w-full rounded border border-border-strong bg-surface px-2 py-1.5"
          />
        </label>

        <label className="mt-3 block text-sm">
          <span className="mb-1 block text-content-muted">Message</span>
          <textarea
            value={body}
            onChange={(event) => {
              setBody(event.target.value);
              setConfirming(false);
            }}
            rows={3}
            aria-label="Announcement message"
            className="w-full rounded border border-border-strong bg-surface px-2 py-1.5"
          />
        </label>

        <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
          <label>
            <span className="mb-1 block text-content-muted">Audience</span>
            <select
              value={audience}
              onChange={(event) => setAudience(event.target.value as "everyone" | "staff")}
              aria-label="Audience"
              className="rounded border border-border-strong bg-surface px-2 py-1"
            >
              <option value="everyone">Everyone</option>
              <option value="staff">Staff only</option>
            </select>
          </label>

          <label>
            <span className="mb-1 block text-content-muted">Schedule for (optional)</span>
            <input
              type="datetime-local"
              value={scheduledFor}
              onChange={(event) => setScheduledFor(event.target.value)}
              aria-label="Schedule for"
              className="rounded border border-border-strong bg-surface px-2 py-1"
            />
          </label>

          <div className="ml-auto">
            {confirming ? (
              <span className="flex items-center gap-2">
                <span className="text-content-muted">
                  {scheduling ? "Schedule it?" : "Send to everyone now?"}
                </span>
                <button
                  type="button"
                  disabled={send.isPending}
                  onClick={() => send.mutate()}
                  className="rounded bg-accent px-3 py-1 text-accent-content disabled:opacity-50"
                >
                  Yes
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="text-content-muted underline"
                >
                  Cancel
                </button>
              </span>
            ) : (
              // Confirmed, because this reaches everyone at once and a stray
              // click is not a good enough reason.
              <button
                type="button"
                disabled={!ready}
                onClick={() => setConfirming(true)}
                className="rounded border border-border px-3 py-1 disabled:opacity-40"
              >
                {scheduling ? "Schedule" : "Send now"}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          History
        </h2>

        {history.isPending ? (
          <Spinner />
        ) : (history.data ?? []).length === 0 ? (
          <p className="mt-3 text-content-muted">Nothing said yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {(history.data ?? []).map((row) => (
              <Row
                key={row.id}
                row={row}
                onCancel={() => cancel.mutate(row.id)}
                onResend={() => {
                  // The honest version of "say it again": a new announcement,
                  // not an edit of one people have read.
                  setTitle(row.title);
                  setBody(row.body);
                  setAudience(row.audience);
                  setScheduledFor("");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function Row({
  row,
  onCancel,
  onResend,
}: {
  row: Announcement;
  onCancel: () => void;
  onResend: () => void;
}) {
  const pending = row.sent_at === null && row.cancelled_at === null;
  const share = row.recipient_count > 0 ? Math.round((row.read_count / row.recipient_count) * 100) : 0;

  return (
    <li className="rounded border border-border bg-surface-raised px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-2">
        <strong className="flex-1">{row.title}</strong>

        {pending && (
          <span className="rounded border border-warning px-1.5 py-0.5 text-xs uppercase tracking-wide text-warning">
            scheduled {row.scheduled_for && new Date(row.scheduled_for).toLocaleString()}
          </span>
        )}
        {row.cancelled_at && (
          <span className="text-xs uppercase tracking-wide text-content-muted">cancelled</span>
        )}
        {row.sent_at && (
          <span className="text-xs text-content-muted">
            {new Date(row.sent_at).toLocaleString()} · {row.recipient_count} sent ·{" "}
            {/* The one genuinely new number: whether the thing you announced
                actually landed. */}
            {row.read_count} read ({share}%)
          </span>
        )}
      </div>

      <p className="mt-1 whitespace-pre-wrap text-content-muted">{row.body}</p>

      <div className="mt-2 flex gap-3 text-xs">
        {row.audience === "staff" && <span className="text-content-muted">staff only</span>}
        {row.created_by_name && (
          <span className="text-content-muted">by {row.created_by_name}</span>
        )}
        {/* No edit and no delete for anything sent: the history is a record of
            what happened. */}
        {pending && (
          <button type="button" onClick={onCancel} className="text-danger underline">
            Cancel
          </button>
        )}
        {row.sent_at && (
          <button type="button" onClick={onResend} className="text-accent-strong underline">
            Say it again
          </button>
        )}
      </div>
    </li>
  );
}
