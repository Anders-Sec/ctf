import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { reportChallenge } from "../api/adminOps";
import ErrorMessage from "./ErrorMessage";

/**
 * "Something's wrong with this challenge."
 *
 * Deliberately understated and tucked below the answer box — it is not an
 * alternative to trying, and a prominent button invites use as a complaint
 * channel. Players who genuinely hit a broken challenge will find it.
 */
export default function ReportChallenge({ challengeId }: { challengeId: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");

  const report = useMutation({ mutationFn: () => reportChallenge(challengeId, message.trim()) });

  if (report.isSuccess) {
    return (
      <p className="mt-6 text-sm text-muted" role="status">
        Reported. An organiser will take a look.
      </p>
    );
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mt-6 text-sm text-muted underline">
        Something's wrong with this challenge
      </button>
    );
  }

  return (
    <form
      className="mt-6 rounded border border-stone bg-white/60 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        report.mutate();
      }}
    >
      <label htmlFor="report-message" className="block text-sm font-medium">
        What's wrong?
      </label>
      <textarea
        id="report-message"
        required
        minLength={5}
        maxLength={1000}
        rows={3}
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        className="mt-1 w-full rounded border border-stone px-3 py-2 text-sm"
        placeholder="The download is corrupt, the answer format is unclear…"
      />
      <div className="mt-2 flex gap-2">
        <button
          type="submit"
          disabled={report.isPending || message.trim().length < 5}
          className="rounded bg-ink px-3 py-1.5 text-sm text-parchment disabled:opacity-50"
        >
          Send report
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm underline">
          Cancel
        </button>
      </div>
      <ErrorMessage error={report.error} />
    </form>
  );
}
