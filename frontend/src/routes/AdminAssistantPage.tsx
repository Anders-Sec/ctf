import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  getFindings,
  RULE_LABELS,
  type AssistantFinding,
  type FindingFilters,
} from "../api/assistantAdmin";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Flagged System AI exchanges, for review after the fact.
 *
 * Like the signals page, the wording matters. A flag is not a verdict: the most
 * common integrity finding is a player making the "just tell me the flag" joke,
 * and the safety findings lean toward "worth a glance" rather than "someone did
 * something wrong". Staff see the withheld reply so a real incident can be read
 * in full — this is the one place that text exists.
 */
export default function AdminAssistantPage() {
  const [filters, setFilters] = useState<FindingFilters>({});

  const findings = useQuery({
    queryKey: ["admin", "assistant", "findings", filters],
    queryFn: () => getFindings(filters),
  });

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">System AI flags</h1>
        <p className="mt-2 text-muted">
          Exchanges the guardrails caught — <strong>not</strong> accusations. Asking the
          System AI for the flag is a joke almost everyone makes, and most of what
          lands here is harmless. A <em>deflected</em> reply was withheld from the player;
          a <em>logged</em> one reached them and is here only for a second look.
        </p>
      </header>

      <div className="mt-6 flex flex-wrap gap-2 text-sm">
        <Toggle
          label="Integrity"
          active={filters.layer === "integrity"}
          onClick={() =>
            setFilters((f) => ({ ...f, layer: f.layer === "integrity" ? undefined : "integrity" }))
          }
        />
        <Toggle
          label="Safety"
          active={filters.layer === "safety"}
          onClick={() =>
            setFilters((f) => ({ ...f, layer: f.layer === "safety" ? undefined : "safety" }))
          }
        />
        <Toggle
          label="Deflected only"
          active={filters.action === "deflected"}
          onClick={() =>
            setFilters((f) => ({
              ...f,
              action: f.action === "deflected" ? undefined : "deflected",
            }))
          }
        />
        <Toggle
          label="Include staff tests"
          active={Boolean(filters.includeStaff)}
          onClick={() => setFilters((f) => ({ ...f, includeStaff: !f.includeStaff }))}
        />
      </div>

      {findings.isPending ? (
        <Spinner label="Reading the ledger…" />
      ) : findings.isError ? (
        <ErrorMessage error={findings.error} />
      ) : findings.data.findings.length === 0 ? (
        <p className="mt-8 text-muted">Nothing flagged.</p>
      ) : (
        <>
          <p className="mt-6 text-sm text-muted">{findings.data.total} flagged in total.</p>
          <ul className="mt-4 space-y-4">
            {findings.data.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
        </>
      )}
    </main>
  );
}

function Toggle({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded border px-3 py-1 ${
        active ? "border-torch bg-torch/10" : "border-stone"
      }`}
    >
      {label}
    </button>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-torch/20 text-torch",
  medium: "bg-stone/40",
  low: "bg-stone/20 text-muted",
};

function FindingCard({ finding }: { finding: AssistantFinding }) {
  return (
    <li className="rounded-lg border border-stone bg-white/40 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs ${SEVERITY_STYLE[finding.severity] ?? ""}`}>
          {finding.severity}
        </span>
        <span className="font-medium">{RULE_LABELS[finding.rule] ?? finding.rule}</span>
        <span className="text-muted">· {finding.layer}</span>
        <span
          className={
            finding.action === "deflected" ? "text-torch" : "text-muted"
          }
        >
          · {finding.action}
        </span>
        <span className="ml-auto text-muted">{finding.player_name}</span>
      </div>

      {finding.question && (
        <p className="mt-3 rounded bg-stone/30 px-3 py-2 text-sm">
          <span className="text-xs uppercase text-muted">Asked</span>
          <br />
          {finding.question}
        </p>
      )}
      {finding.reply && (
        <p className="mt-2 rounded bg-white/70 px-3 py-2 text-sm">
          <span className="text-xs uppercase text-muted">
            {finding.action === "deflected" ? "Withheld reply" : "Reply"}
          </span>
          <br />
          {finding.reply}
        </p>
      )}
    </li>
  );
}
