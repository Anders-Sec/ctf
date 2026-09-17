import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getPlatformHealth, type HealthCheck } from "../api/adminHealth";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Platform Health (spec 057).
 *
 * Not observability — `Plan.md` rules a metrics stack out for a five-day
 * single-instance event, and this is what that implies: one screen, read when
 * something feels wrong. The bar it clears is that a player saying "it's
 * broken" can be answered in ten seconds with "the platform, that challenge, or
 * you".
 *
 * Polled only while open. No background sweep, no stored history: this is a
 * screen you look at, not a system that watches.
 */

const REFRESH_MS = 15_000;

/** Where to go next after a red light — always the same answer. */
const FOLLOW_UP: Record<string, { to: string; label: string }> = {
  "Model host": { to: "/admin/assistant", label: "System AI" },
  Orchestrator: { to: "/admin/instances", label: "Live Instances" },
  "Mail relay": { to: "/admin/email", label: "Email Delivery" },
};

export default function AdminHealthPage() {
  const health = useQuery({
    queryKey: ["admin", "platform-health"],
    queryFn: getPlatformHealth,
    refetchInterval: REFRESH_MS,
  });

  if (health.isPending) return <Spinner label="Taking a pulse…" />;
  if (health.isError) return <ErrorMessage error={health.error} />;

  const { checks, connections, build, load, checked_at } = health.data;

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Platform Health</h1>
          <p className="mt-2 text-sm text-content-muted">
            Is the platform unwell, or is it the event? Figures below are for this process only.
          </p>
        </div>
        <span className="text-sm text-content-muted">
          checked {new Date(checked_at).toLocaleTimeString()}
        </span>
      </header>

      <section className="mt-6 rounded border border-border bg-surface-raised">
        <ul>
          {checks.map((check) => (
            <CheckRow key={check.name} check={check} />
          ))}
        </ul>
      </section>

      <section className="mt-6 grid gap-3 sm:grid-cols-3">
        <Panel title="Connections">
          <Line label="Scoreboard sockets" value={String(connections.scoreboard)} />
        </Panel>

        <Panel title="Build">
          <Line label="Version" value={build.version} />
          <Line label="Environment" value={build.environment} />
          {/* Answers "did something restart?", which is the second question
              after every unexplained weirdness. */}
          <Line label="Uptime" value={humanUptime(load.uptime_seconds)} />
        </Panel>

        <Panel title={`Load · last ${load.window_minutes}m`}>
          <Line label="Requests/min" value={String(load.requests_per_minute)} />
          <Line label="p95" value={`${load.p95_ms} ms`} />
          <Line label="5xx" value={String(load.errors)} tone={load.errors > 0} />
        </Panel>
      </section>

      <p className="mt-6 text-xs text-content-muted">
        Counters live in this process: they reset when it restarts, and with more than one replica
        they describe whichever one answered. Aggregating across replicas is what a metrics stack
        is for, and we deliberately do not run one for a five-day event.
      </p>
    </main>
  );
}

function CheckRow({ check }: { check: HealthCheck }) {
  const follow = FOLLOW_UP[check.name];

  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5 text-sm last:border-b-0">
      {/* A word, not a colour. The dot is the fast path for whoever can use it. */}
      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${dotFor(check.state)}`} />
      <span className="w-36 shrink-0 font-medium">{check.name}</span>
      <span className={`w-32 shrink-0 ${textFor(check.state)}`}>
        {check.state.replace("_", " ")}
      </span>
      <span className="w-16 shrink-0 text-right tabular-nums text-content-muted">
        {check.duration_ms === null ? "" : `${check.duration_ms} ms`}
      </span>
      <span className="flex-1 text-content-muted">{check.detail ?? ""}</span>
      {follow && (
        <Link to={follow.to} className="shrink-0 text-xs text-accent-strong underline">
          {follow.label}
        </Link>
      )}
    </li>
  );
}

function dotFor(state: string): string {
  if (state === "ok") return "bg-success";
  if (state === "degraded") return "bg-warning";
  if (state === "down") return "bg-danger";
  return "bg-content-faint";
}

function textFor(state: string): string {
  if (state === "ok") return "text-success";
  if (state === "degraded") return "text-warning";
  if (state === "down") return "text-danger";
  return "text-content-muted";
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Line({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <p className="flex justify-between gap-2 text-sm">
      <span className="text-content-muted">{label}</span>
      <span className={`tabular-nums ${tone ? "text-danger" : ""}`}>{value}</span>
    </p>
  );
}

function humanUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}
