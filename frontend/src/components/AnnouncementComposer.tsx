import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { sendAnnouncement } from "../api/announcements";
import ErrorMessage from "./ErrorMessage";

/**
 * Speaking to the whole event (spec 032).
 *
 * Two deliberate frictions. It asks for confirmation, because this reaches
 * every player at once and a stray click is not a good enough reason. And it
 * says plainly that the message cannot be recalled — deleting something people
 * have already read would be a lie about what happened, so a correction is
 * another announcement.
 */
export default function AnnouncementComposer() {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [sentTo, setSentTo] = useState<number | null>(null);

  const send = useMutation({
    mutationFn: () => sendAnnouncement({ title: title.trim(), body: body.trim() }),
    onSuccess: (result) => {
      setSentTo(result.recipients);
      setTitle("");
      setBody("");
      setConfirming(false);
    },
  });

  const ready = title.trim().length >= 3 && body.trim().length >= 3;

  return (
    <section className="mt-8 rounded border border-border bg-surface-raised p-4">
      <h2 className="text-lg font-semibold">Announce to everyone</h2>
      <p className="mt-1 text-sm text-content-muted">
        Goes to every active player in the System AI&apos;s voice, and appears in
        their feed immediately. It cannot be taken back — a correction is another
        announcement.
      </p>

      <div className="mt-3 space-y-3">
        <label className="block text-sm">
          <span className="mb-1 block text-content-muted">Title</span>
          <input
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setConfirming(false);
            }}
            aria-label="Announcement title"
            className="w-full rounded border border-border px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-content-muted">Message</span>
          <textarea
            value={body}
            onChange={(event) => {
              setBody(event.target.value);
              setConfirming(false);
            }}
            rows={3}
            aria-label="Announcement message"
            className="w-full rounded border border-border px-2 py-1.5"
          />
        </label>
      </div>

      <ErrorMessage error={send.error} />

      {sentTo !== null && (
        <p className="mt-3 rounded border border-border bg-surface-raised px-3 py-2 text-sm">
          Sent to {sentTo} {sentTo === 1 ? "player" : "players"}.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {confirming ? (
          <>
            <span className="text-sm font-semibold">
              This reaches every player and cannot be recalled. Send it?
            </span>
            <button
              onClick={() => send.mutate()}
              disabled={send.isPending}
              className="rounded bg-content px-4 py-2 text-sm text-surface disabled:opacity-50"
            >
              {send.isPending ? "Sending…" : "Yes, send it"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-sm hover:underline"
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            onClick={() => {
              setSentTo(null);
              setConfirming(true);
            }}
            disabled={!ready}
            className="rounded bg-content px-4 py-2 text-sm text-surface disabled:opacity-50"
          >
            Send announcement
          </button>
        )}
      </div>
    </section>
  );
}
