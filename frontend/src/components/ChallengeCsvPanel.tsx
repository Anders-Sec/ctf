import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  EXPORT_URL,
  TEMPLATE_URL,
  importChallenges,
  type ImportReport,
} from "../api/challengeCsv";
import ErrorMessage from "./ErrorMessage";

/**
 * Planning an event in a spreadsheet rather than in 242 web forms (specs 026, 040).
 *
 * The template arrives with every category, a suggested difficulty and the XP
 * that difficulty is worth already filled in, so doing nothing but writing
 * titles and flags produces an event whose economy already matches the curve
 * levels were tuned against.
 *
 * Since 040 the file carries everything: several flags with their match types,
 * hints, prerequisites and boss tiers all ride along as JSON in one cell each.
 */
export default function ChallengeCsvPanel() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [report, setReport] = useState<ImportReport | null>(null);

  const upload = useMutation({
    mutationFn: () => importChallenges(file!, dryRun),
    onSuccess: (result) => {
      setReport(result);
      if (!result.dry_run) queryClient.invalidateQueries();
    },
  });

  return (
    <section className="mt-8 rounded border border-stone bg-white/40 p-4">
      <h2 className="text-lg font-semibold">Challenges as CSV</h2>
      <p className="mt-1 text-sm text-muted">
        The template has a row for every challenge, with the category,
        difficulty and its suggested XP already filled in — write the rest in a
        spreadsheet and upload it back. A row carries everything a challenge
        has: several flags with their match types, hints, prerequisites and a
        boss tier. Re-uploading an edited file updates rather than duplicating,
        and a <code>slug</code> lets a title be renamed without creating a
        second challenge. Imported challenges arrive as drafts; artifacts stay
        in the platform.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {/* Plain links: the browser saves from Content-Disposition, which a
            fetch would have to reimplement. */}
        <a
          href={TEMPLATE_URL}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment hover:opacity-90"
        >
          Download template
        </a>
        <a
          href={EXPORT_URL}
          className="rounded border border-stone px-4 py-2 text-sm hover:bg-white/60"
        >
          Export current
        </a>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          aria-label="CSV file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setReport(null);
          }}
          className="text-sm"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(event) => setDryRun(event.target.checked)}
          />
          Dry run (check without writing)
        </label>
        <button
          onClick={() => upload.mutate()}
          disabled={!file || upload.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          {upload.isPending ? "Reading…" : dryRun ? "Check file" : "Import"}
        </button>
      </div>

      <ErrorMessage error={upload.error} />

      {report && (
        <div className="mt-4 text-sm">
          <p>
            {report.dry_run ? "Would create" : "Created"}{" "}
            <strong>{report.created}</strong>,{" "}
            {report.dry_run ? "update" : "updated"}{" "}
            <strong>{report.updated}</strong>, skipped{" "}
            <strong>{report.skipped}</strong> blank{" "}
            {report.skipped === 1 ? "row" : "rows"}.
          </p>

          {report.errors.length > 0 && (
            <>
              <p className="mt-2 text-muted">
                Nothing was written — the whole file is refused if any row is
                wrong, so a half-imported event cannot happen.
              </p>
              <table className="mt-2 w-full border-collapse text-left">
                <thead>
                  <tr className="text-muted">
                    <th className="border-b border-stone py-1 pr-3">Row</th>
                    <th className="border-b border-stone py-1 pr-3">Column</th>
                    <th className="border-b border-stone py-1">Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {report.errors.map((error, index) => (
                    <tr key={`${error.row}-${error.column}-${index}`}>
                      <td className="border-b border-stone/50 py-1 pr-3 tabular-nums">
                        {error.row}
                      </td>
                      <td className="border-b border-stone/50 py-1 pr-3">
                        {error.column}
                      </td>
                      <td className="border-b border-stone/50 py-1">{error.problem}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </section>
  );
}
