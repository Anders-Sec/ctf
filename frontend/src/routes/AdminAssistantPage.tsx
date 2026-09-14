import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  acknowledgeFinding,
  getFindings,
  getHealth,
  getMetrics,
  getSessions,
  getTermsSummary,
  getTranscript,
  purgeConversations,
  RULE_LABELS,
  setAssistantBlock,
  type AssistantFinding,
  type FindingFilters,
  type Rung,
  type Session,
} from "../api/assistantAdmin";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/** The event console's cadence. An operations page need not be live to the second. */
const REFRESH_MS = 10_000;

type Tab = "health" | "flags" | "sessions";

/**
 * The System AI console (spec 034).
 *
 * Three questions, answerable without reading logs: is it up, what are the
 * guardrails catching, and what is this player doing.
 *
 * The tone matters and is inherited from specs 007 and 011: a flag is **not a
 * verdict**. With the ladder that is more true, not less — every player is now
 * supposed to attack the AI. The safety findings are the ones that want a human,
 * so those get the visual weight; the rest is background.
 */
export default function AdminAssistantPage() {
  const [tab, setTab] = useState<Tab>("health");

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">System AI</h1>
        <p className="mt-2 text-muted">
          Health, what the guardrails caught, and who is talking to it.
        </p>
      </header>

      <nav className="mt-6 flex gap-2 border-b border-stone text-sm">
        {(["health", "flags", "sessions"] as const).map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            aria-current={tab === name ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 capitalize ${
              tab === name ? "border-torch font-medium" : "border-transparent text-muted"
            }`}
          >
            {name}
          </button>
        ))}
      </nav>

      {tab === "health" && <HealthSection />}
      {tab === "flags" && <FlagsSection />}
      {tab === "sessions" && <SessionsSection />}
    </main>
  );
}

// --- Health -----------------------------------------------------------------

function HealthSection() {
  // Polled only while this section is on screen: a dashboard nobody is looking
  // at should not be hitting a model host every ten seconds from two replicas.
  const health = useQuery({
    queryKey: ["admin", "assistant", "health"],
    queryFn: getHealth,
    refetchInterval: REFRESH_MS,
  });
  const metrics = useQuery({
    queryKey: ["admin", "assistant", "metrics"],
    queryFn: getMetrics,
    refetchInterval: REFRESH_MS,
  });
  const terms = useQuery({
    queryKey: ["admin", "assistant", "terms"],
    queryFn: () => getTermsSummary(),
  });

  if (health.isPending || metrics.isPending) return <Spinner label="Taking a pulse…" />;
  if (health.isError) return <ErrorMessage error={health.error} />;
  if (metrics.isError) return <ErrorMessage error={metrics.error} />;

  const state = health.data;
  const window = metrics.data.windows["15m"];
  if (!window) return <ErrorMessage error={new Error("No metrics window returned.")} />;

  return (
    <div className="mt-6 space-y-8">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded px-2 py-0.5 text-sm ${
              state.reachable ? "bg-stone/40" : "bg-torch/20 text-torch"
            }`}
          >
            {state.reachable ? "reachable" : "unreachable"}
          </span>
          {state.breaker_open && (
            <span className="rounded bg-torch/20 px-2 py-0.5 text-sm text-torch">
              breaker open · {state.retry_after_seconds}s
            </span>
          )}
          {!state.enabled && (
            <span className="rounded bg-stone/40 px-2 py-0.5 text-sm">switched off</span>
          )}
          <span className="text-sm text-muted">{state.model ?? "no model configured"}</span>
        </div>
        {/*
          The breaker, the in-flight count and the recent latency live in process
          memory, and the deployment runs two replicas. A refresh can legitimately
          show different numbers. Labelled rather than hidden: a wrong number
          nobody can interpret is worse than a right one that says whose it is.
        */}
        <p className="mt-2 text-xs text-muted">
          Reachability, breaker and in-flight are <strong>per replica</strong> — whichever
          answered this request. Two are running, so these can legitimately differ
          between refreshes. Everything below comes from the database and does not.
        </p>
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Last 15 minutes
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Turns" value={window.turns} />
          <Stat label="Active sessions" value={window.active_sessions} />
          <Stat
            label="Median latency"
            value={window.median_latency_ms === null ? "—" : `${window.median_latency_ms}ms`}
          />
          <Stat
            label="p95 latency"
            value={window.p95_latency_ms === null ? "—" : `${window.p95_latency_ms}ms`}
          />
          <Stat
            label="Calls per turn"
            value={window.calls_per_turn === null ? "—" : window.calls_per_turn}
            hint="A level 5 turn costs five, and each takes one of eight slots."
          />
          <Stat label="Deflected" value={window.deflections} />
          <Stat label="Errors" value={window.errors} />
          <Stat label="In flight" value={state.in_flight} />
        </div>
      </section>

      {Object.keys(metrics.data.errors_by_reason).length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
            Failures · last hour
          </h2>
          <ul className="mt-2 flex flex-wrap gap-2 text-sm">
            {Object.entries(metrics.data.errors_by_reason).map(([reason, count]) => (
              <li key={reason} className="rounded border border-stone px-2 py-1">
                {reason} · <strong>{count}</strong>
              </li>
            ))}
          </ul>
        </section>
      )}

      <LadderTable rungs={metrics.data.rungs} />

      <section className="rounded-lg border border-stone bg-white/40 p-4 text-sm">
        <h2 className="font-semibold">Terms of use</h2>
        {terms.data ? (
          <>
            <p className="mt-1 text-muted">
              <strong>{terms.data.accepted}</strong> accepted,{" "}
              <strong>{terms.data.outstanding}</strong> outstanding · version{" "}
              <code className="rounded bg-stone/30 px-1">{terms.data.version}</code>
            </p>
            <p className="mt-2 text-xs text-muted">
              The version is the hash of the terms file. Editing it is a new version and
              everyone accepts again — their last acceptance was to different words.
            </p>
          </>
        ) : (
          <p className="mt-1 text-torch">
            The terms file could not be read, so the System AI is refusing everyone.
          </p>
        )}
      </section>

      <RetentionPanel />
    </div>
  );
}

function LadderTable({ rungs }: { rungs: Rung[] }) {
  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">The ladder</h2>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-muted">
            <tr>
              <th className="py-1">Rung</th>
              <th>Players</th>
              <th>Turns</th>
              <th>Solves</th>
              <th>Decoys</th>
              <th>Gates fired</th>
            </tr>
          </thead>
          <tbody>
            {rungs.map((rung) => (
              <tr key={rung.level} className="border-t border-stone/60">
                <td className="py-1.5">
                  {rung.level} · {rung.name}
                </td>
                <td>{rung.players}</td>
                <td>{rung.turns}</td>
                <td>{rung.solves}</td>
                {/* Near zero, or the model has started inventing flags. */}
                <td className={rung.decoys > 0 ? "font-semibold text-torch" : ""}>
                  {rung.decoys}
                </td>
                <td className="text-muted">
                  {Object.entries(rung.gates)
                    .map(([gate, count]) => `${gate} ${count}`)
                    .join(" · ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RetentionPanel() {
  const [purged, setPurged] = useState<number | null>(null);
  const purge = useMutation({
    mutationFn: purgeConversations,
    onSuccess: (result) => setPurged(result.purged),
  });

  return (
    <section className="rounded-lg border border-stone bg-white/40 p-4 text-sm">
      <h2 className="font-semibold">Retention</h2>
      <p className="mt-1 text-muted">
        Removes conversations older than the retention window. Findings survive — they
        record that something happened, and never contain an answer.
      </p>
      {purged !== null && (
        <p className="mt-2" role="status">
          Removed {purged} conversation{purged === 1 ? "" : "s"}.
        </p>
      )}
      {purge.isError && <ErrorMessage error={purge.error} />}
      <button
        onClick={() => purge.mutate()}
        disabled={purge.isPending}
        className="mt-3 rounded border border-stone px-3 py-1 disabled:opacity-50"
      >
        {purge.isPending ? "Purging…" : "Purge expired conversations"}
      </button>
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-stone bg-white/40 p-3" title={hint}>
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

// --- Flags ------------------------------------------------------------------

function FlagsSection() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<FindingFilters>({ unreviewed: true });

  const findings = useQuery({
    queryKey: ["admin", "assistant", "findings", filters],
    queryFn: () => getFindings(filters),
  });
  const metrics = useQuery({
    queryKey: ["admin", "assistant", "metrics"],
    queryFn: getMetrics,
  });

  const acknowledge = useMutation({
    mutationFn: acknowledgeFinding,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "assistant"] });
    },
  });

  return (
    <div className="mt-6">
      <p className="text-muted">
        Exchanges the guardrails caught — <strong>not</strong> accusations. Every player is
        meant to attack the System AI; that is the challenge. A <em>deflected</em> reply was
        withheld; a <em>logged</em> one reached them and is here for a second look.
      </p>

      {metrics.data && Object.keys(metrics.data.findings_by_rule).length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2 text-sm">
          {Object.entries(metrics.data.findings_by_rule).map(([rule, count]) => (
            <li key={rule}>
              <button
                onClick={() =>
                  setFilters((f) => ({ ...f, rule: f.rule === rule ? undefined : rule }))
                }
                aria-pressed={filters.rule === rule}
                className={`rounded border px-2 py-1 ${
                  filters.rule === rule ? "border-torch bg-torch/10" : "border-stone"
                }`}
              >
                {RULE_LABELS[rule] ?? rule} · <strong>{count}</strong>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap gap-2 text-sm">
        <Toggle
          label="Unreviewed only"
          active={Boolean(filters.unreviewed)}
          onClick={() => setFilters((f) => ({ ...f, unreviewed: !f.unreviewed }))}
        />
        <Toggle
          label="Safety"
          active={filters.layer === "safety"}
          onClick={() =>
            setFilters((f) => ({ ...f, layer: f.layer === "safety" ? undefined : "safety" }))
          }
        />
        <Toggle
          label="High severity"
          active={filters.severity === "high"}
          onClick={() =>
            setFilters((f) => ({ ...f, severity: f.severity === "high" ? undefined : "high" }))
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
          <p className="mt-6 text-sm text-muted">{findings.data.total} matching.</p>
          <ul className="mt-4 space-y-4">
            {findings.data.findings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                onAcknowledge={() => acknowledge.mutate(finding.id)}
              />
            ))}
          </ul>
        </>
      )}
    </div>
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
      className={`rounded border px-3 py-1 ${active ? "border-torch bg-torch/10" : "border-stone"}`}
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

function FindingCard({
  finding,
  onAcknowledge,
}: {
  finding: AssistantFinding;
  onAcknowledge: () => void;
}) {
  return (
    <li
      className={`rounded-lg border bg-white/40 p-4 ${
        // The safety layer is what actually wants a human. Ladder noise is background.
        finding.layer === "safety" ? "border-torch/50" : "border-stone"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs ${SEVERITY_STYLE[finding.severity] ?? ""}`}>
          {finding.severity}
        </span>
        <span className="font-medium">{RULE_LABELS[finding.rule] ?? finding.rule}</span>
        <span className="text-muted">· {finding.layer}</span>
        <span className={finding.action === "deflected" ? "text-torch" : "text-muted"}>
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

      <div className="mt-3 text-sm">
        {finding.acknowledged_at ? (
          <span className="text-muted">Seen.</span>
        ) : (
          <button onClick={onAcknowledge} className="rounded border border-stone px-2 py-1">
            Mark as seen
          </button>
        )}
      </div>
    </li>
  );
}

// --- Sessions ---------------------------------------------------------------

function SessionsSection() {
  const [minutes, setMinutes] = useState<number | null>(30);
  const [openFor, setOpenFor] = useState<Session | null>(null);

  const sessions = useQuery({
    queryKey: ["admin", "assistant", "sessions", minutes],
    queryFn: () => getSessions(minutes),
    refetchInterval: REFRESH_MS,
  });

  if (openFor) {
    return <TranscriptView session={openFor} onBack={() => setOpenFor(null)} />;
  }

  return (
    <div className="mt-6">
      <p className="text-muted">
        Who is talking to the System AI. Opening a transcript is recorded — it is a
        troubleshooting tool, and players are told their conversation is readable.
      </p>

      <div className="mt-4 flex gap-2 text-sm">
        <Toggle label="Last 30 minutes" active={minutes === 30} onClick={() => setMinutes(30)} />
        <Toggle label="Whole event" active={minutes === null} onClick={() => setMinutes(null)} />
      </div>

      {sessions.isPending ? (
        <Spinner label="Looking around…" />
      ) : sessions.isError ? (
        <ErrorMessage error={sessions.error} />
      ) : sessions.data.sessions.length === 0 ? (
        <p className="mt-8 text-muted">Nobody is talking to it.</p>
      ) : (
        <ul className="mt-4 divide-y divide-stone/60">
          {sessions.data.sessions.map((session) => (
            <li key={session.user_id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <span className="font-medium">{session.player_name}</span>
              <span className="text-muted">rung {session.ladder_level}</span>
              <span className="text-muted">{session.turns} turns</span>
              {session.findings > 0 && (
                <span className="rounded bg-torch/15 px-2 py-0.5 text-xs text-torch">
                  {session.findings} flagged
                </span>
              )}
              {session.blocked && (
                <span className="rounded bg-stone/40 px-2 py-0.5 text-xs">blocked</span>
              )}
              <button
                onClick={() => setOpenFor(session)}
                className="ml-auto rounded border border-stone px-2 py-1"
              >
                Open transcript
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TranscriptView({ session, onBack }: { session: Session; onBack: () => void }) {
  const queryClient = useQueryClient();
  const transcript = useQuery({
    queryKey: ["admin", "assistant", "transcript", session.user_id],
    queryFn: () => getTranscript(session.user_id),
  });

  const block = useMutation({
    mutationFn: (blocked: boolean) => setAssistantBlock(session.user_id, blocked),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "assistant", "sessions"] });
    },
  });

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={onBack} className="rounded border border-stone px-2 py-1 text-sm">
          Back
        </button>
        <h2 className="text-lg font-semibold">{session.player_name}</h2>
        <button
          onClick={() => block.mutate(!session.blocked)}
          disabled={block.isPending}
          className="ml-auto rounded border border-stone px-2 py-1 text-sm disabled:opacity-50"
        >
          {session.blocked ? "Allow the System AI" : "Take the System AI away"}
        </button>
      </div>

      {transcript.isPending ? (
        <Spinner label="Pulling the tape…" />
      ) : transcript.isError ? (
        <ErrorMessage error={transcript.error} />
      ) : !transcript.data.exists ? (
        <p className="mt-8 text-muted">
          This conversation has been purged by retention. Any findings from it survive on
          the Flags tab.
        </p>
      ) : (
        <ol className="mt-4 space-y-3">
          {transcript.data.turns.map((turn) => (
            <li
              key={turn.id}
              className={`rounded border p-3 text-sm ${
                turn.role === "user" ? "border-stone bg-stone/20" : "border-stone bg-white/50"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="uppercase">{turn.role}</span>
                {turn.ladder_level !== null && <span>· rung {turn.ladder_level}</span>}
                {turn.trace && turn.trace.length > 0 && <span>· {turn.trace.join(", ")}</span>}
                {turn.latency_ms !== null && <span>· {turn.latency_ms}ms</span>}
                {turn.upstream_calls !== null && <span>· {turn.upstream_calls} calls</span>}
                {turn.error && <span className="text-torch">· {turn.error}</span>}
              </div>

              <p className="mt-2 whitespace-pre-wrap">{turn.content}</p>

              {turn.original_content && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-torch">
                    Withheld reply — what the player did not see
                  </summary>
                  <p className="mt-1 whitespace-pre-wrap rounded bg-torch/10 p-2 text-sm">
                    {turn.original_content}
                  </p>
                </details>
              )}

              {/*
                Spec 010 keeps this so an odd answer can be explained, and returns
                it nowhere else. On the ladder it routinely contains the flag the
                model was protecting — collapsed, so it is a decision to read.
              */}
              {turn.reasoning_content && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-muted">
                    Model reasoning — may contain live flag values
                  </summary>
                  <p className="mt-1 whitespace-pre-wrap rounded bg-stone/20 p-2 text-xs">
                    {turn.reasoning_content}
                  </p>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
