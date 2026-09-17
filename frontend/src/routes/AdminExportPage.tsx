import { useState } from "react";

/**
 * Event export (spec 056).
 *
 * Content export was already solved — an event can be rebuilt. Nothing exported
 * what *happened*, so after five days the only way to get the standings out was
 * a screenshot.
 *
 * Plain links rather than fetch-and-blob: the browser already knows how to
 * download a file, and a streamed multi-megabyte CSV should not be buffered
 * through JavaScript to arrive at the same place.
 */

interface Export {
  name: string;
  label: string;
  summary: string;
}

const EXPORTS: Export[] = [
  {
    name: "standings",
    label: "Final standings",
    summary: "Both boards with rank, solves, the adjustment split and tie-break timestamps.",
  },
  {
    name: "awards",
    label: "Awards sheet",
    summary: "Overall, top per zone, first bloods and completionists — grouped to be read aloud.",
  },
  {
    name: "solves",
    label: "Solves",
    summary: "One row per solve: player, party at the time, challenge, zone, XP.",
  },
  {
    name: "submissions",
    label: "Submissions",
    summary: "Every attempt, with what was typed replaced by its length and near-miss distance.",
  },
  {
    name: "players",
    label: "Players",
    summary: "The roster with source, party, XP and sign-in history.",
  },
  {
    name: "parties",
    label: "Parties",
    summary: "Every party including disbanded ones — they are part of what happened.",
  },
  {
    name: "adjustments",
    label: "Score adjustments",
    summary: "Every manual change with its reason, who made it, and whether it was reversed.",
  },
  { name: "audit-log", label: "Audit log", summary: "Every consequential action, in full." },
];

export default function AdminExportPage() {
  const [confirmingFull, setConfirmingFull] = useState(false);

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Export</h1>
        <p className="mt-2 text-sm text-content-muted">
          Results, not content. Available whenever — checking that the awards sheet computes what
          you expect is a thing to do before the afternoon you need it.
        </p>
      </header>

      <ul className="mt-6 flex flex-col gap-2">
        {EXPORTS.map((item) => (
          <li
            key={item.name}
            className="flex items-center gap-4 rounded border border-border bg-surface-raised px-4 py-3"
          >
            <span className="flex-1">
              <strong className="text-sm">{item.label}</strong>
              <span className="block text-xs text-content-muted">{item.summary}</span>
            </span>
            <a
              href={`/api/admin/export/${item.name}.csv`}
              className="shrink-0 rounded border border-border px-3 py-1 text-sm hover:bg-surface-sunken"
            >
              CSV
            </a>
          </li>
        ))}
      </ul>

      <section className="mt-8 rounded border border-border bg-surface-raised p-4">
        <h2 className="text-sm font-semibold">Everything</h2>
        <p className="mt-1 text-xs text-content-muted">
          All of the above in one zip, with a manifest naming the event, the window and the row
          count of each file.
        </p>
        <a
          href="/api/admin/export/archive.zip"
          className="mt-3 inline-block rounded bg-accent px-3 py-1.5 text-sm text-accent-content"
        >
          Download archive
        </a>
      </section>

      <section className="mt-8 rounded border border-danger/50 p-4">
        <h2 className="text-sm font-semibold text-danger">Full submissions</h2>
        <p className="mt-1 text-xs text-content-muted">
          Every attempt verbatim, plus addresses. In aggregate this file is{" "}
          <strong>a list of every flag in the event</strong>, because every correct submission is
          one. Legitimate for post-event analysis; not a file to email around. Taking it is
          recorded in the audit log.
        </p>

        {confirmingFull ? (
          <span className="mt-3 flex items-center gap-3 text-sm">
            <a
              href="/api/admin/export/submissions-full.csv"
              onClick={() => setConfirmingFull(false)}
              className="rounded border border-danger px-3 py-1 text-danger"
            >
              I understand — download it
            </a>
            <button
              type="button"
              onClick={() => setConfirmingFull(false)}
              className="text-content-muted underline"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingFull(true)}
            className="mt-3 rounded border border-border px-3 py-1 text-sm"
          >
            Export full submissions
          </button>
        )}
      </section>
    </main>
  );
}
