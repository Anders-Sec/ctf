import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getChallengeHealth, getDashboard, type ChallengeHealth } from "../api/adminOps";
import ErrorMessage from "../components/ErrorMessage";
import SampleDataPanel from "../components/SampleDataPanel";
import Spinner from "../components/Spinner";

/** Refreshed on a timer. An operations console does not need to be live to the second. */
const REFRESH_MS = 10_000;

export default function AdminDashboardPage() {
  const dashboard = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: getDashboard,
    refetchInterval: REFRESH_MS,
  });
  const health = useQuery({
    queryKey: ["admin", "challenge-health"],
    queryFn: getChallengeHealth,
    refetchInterval: REFRESH_MS,
  });

  if (dashboard.isPending) return <Spinner label="Reading the room…" />;
  if (dashboard.isError) return <ErrorMessage error={dashboard.error} />;

  const data = dashboard.data;
  const attention = data.attention;
  const needsAttention =
    attention.open_reports +
    attention.pending_approvals +
    attention.drafts_after_start +
    attention.published_without_answers.length +
    attention.suspected_broken.length;

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Event console</h1>
          <p className="mt-1 text-muted">
            {data.event.name ?? "Unnamed event"} ·{" "}
            {data.event.running ? "running" : "not running"}
          </p>
        </div>
        <span className="text-sm text-muted">
          refreshed {new Date(data.generated_at).toLocaleTimeString()}
        </span>
      </header>

      <section className="mt-6 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Solves · 5 min" value={data.pulse.solves_5m} />
        <Stat label="Solves · 15 min" value={data.pulse.solves_15m} />
        <Stat label="Solves · 1 hr" value={data.pulse.solves_60m} />
        <Stat label="Attempts · 15 min" value={data.pulse.submissions_15m} />
        <Stat label="Active players" value={data.pulse.active_players_15m} />
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Needs attention {needsAttention > 0 && `(${needsAttention})`}
        </h2>

        {needsAttention === 0 ? (
          <p className="mt-3 text-muted">Nothing is on fire.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {attention.suspected_broken.map((item) => (
              <Alert key={item.challenge_id} tone="urgent">
                <strong>{item.title}</strong> — {item.attempts} attempts, nobody has solved it.
                The answer rule is probably wrong.
              </Alert>
            ))}
            {attention.published_without_answers.map((item) => (
              <Alert key={item.challenge_id} tone="urgent">
                <strong>{item.title}</strong> is published with no answer rules — it cannot be
                solved.
              </Alert>
            ))}
            {attention.open_reports > 0 && (
              <Alert tone="normal">
                {attention.open_reports} open{" "}
                {attention.open_reports === 1 ? "report" : "reports"} from players ·{" "}
                <Link to="/admin/ops" className="underline">
                  triage
                </Link>
              </Alert>
            )}
            {attention.pending_approvals > 0 && (
              <Alert tone="normal">
                {attention.pending_approvals} waiting for approval ·{" "}
                <Link to="/admin/users" className="underline">
                  review
                </Link>
              </Alert>
            )}
            {attention.drafts_after_start > 0 && (
              <Alert tone="normal">
                {attention.drafts_after_start} challenges still in draft, and the event has
                started.
              </Alert>
            )}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Challenge health
        </h2>
        <ErrorMessage error={health.error} />
        {health.data && <HealthTable rows={health.data} />}
      </section>

      <section className="mt-8 rounded-lg border border-dashed border-stone p-4 text-sm text-muted">
        <strong className="text-ink">Containers</strong> — {data.containers.note}
      </section>

      <SampleDataPanel />
    </main>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-stone bg-white/60 p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function Alert({ children, tone }: { children: React.ReactNode; tone: "urgent" | "normal" }) {
  return (
    <li
      className={`rounded border px-3 py-2 text-sm ${
        tone === "urgent" ? "border-torch/50 bg-torch/10" : "border-stone bg-white/60"
      }`}
    >
      {children}
    </li>
  );
}

function HealthTable({ rows }: { rows: ChallengeHealth[] }) {
  if (rows.length === 0) {
    return <p className="mt-3 text-muted">No challenges yet.</p>;
  }

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-muted">
          <tr>
            <th className="py-2">Challenge</th>
            <th className="py-2">State</th>
            <th className="py-2 text-right">Solves</th>
            <th className="py-2 text-right">Attempts</th>
            <th className="py-2 text-right">Reports</th>
            <th className="py-2">Signal</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.challenge_id} className="border-t border-stone">
              <td className="py-2">{row.title}</td>
              <td className="py-2 text-muted">{row.state}</td>
              <td className="py-2 text-right tabular-nums">{row.solve_count}</td>
              <td className="py-2 text-right tabular-nums">{row.attempt_count}</td>
              <td className="py-2 text-right tabular-nums">{row.open_reports || ""}</td>
              <td className="py-2">
                {row.suspected_broken && (
                  <span className="text-torch">likely broken</span>
                )}
                {row.suspiciously_easy && (
                  <span className="text-torch">answer may have leaked</span>
                )}
                {/* An untouched challenge is untouched, not a 0% success rate. */}
                {row.attempt_count === 0 && <span className="text-muted">untouched</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
