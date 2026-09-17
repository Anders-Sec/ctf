import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  getChallengeMetrics,
  getPlayerMetrics,
  getProgression,
  getPulse,
  type ChallengeMetric,
  type StalledPlayer,
} from "../api/adminMetrics";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Event metrics (spec 050).
 *
 * The dashboard is the smoke alarm — it catches a challenge with ninety
 * attempts and no solves. This is the slower question: is anything *drifting*?
 * A challenge twice as hard as intended still produces solves, so it never
 * trips the alarm; it just quietly eats a day.
 */

const WINDOWS = [
  { id: "1h", label: "Last hour" },
  { id: "4h", label: "Last 4 hours" },
  { id: "today", label: "Today" },
  { id: "event", label: "Whole event" },
] as const;

const PLAYER_FILTERS = [
  { id: "stuck", label: "Stuck", hint: "Submitting, not solving, for over an hour" },
  { id: "quiet", label: "Gone quiet", hint: "Active earlier, nothing for two hours" },
  { id: "never_started", label: "Never started", hint: "Approved, zero submissions all event" },
] as const;

export default function AdminMetricsPage() {
  const [window, setWindow] = useState<string>("today");
  const [playerFilter, setPlayerFilter] = useState<string>("stuck");

  const pulse = useQuery({
    queryKey: ["admin", "metrics", "pulse", window],
    queryFn: () => getPulse(window),
  });
  const challenges = useQuery({
    queryKey: ["admin", "metrics", "challenges", window],
    queryFn: () => getChallengeMetrics(window),
  });
  const players = useQuery({
    queryKey: ["admin", "metrics", "players", playerFilter],
    queryFn: () => getPlayerMetrics(playerFilter),
  });
  const progression = useQuery({
    queryKey: ["admin", "metrics", "progression"],
    queryFn: getProgression,
  });

  return (
    <main className="p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Metrics</h1>
          <p className="mt-2 text-sm text-content-muted">
            For spotting a problem early enough to fix it. Figures are cached for a minute.
          </p>
        </div>
        <div className="flex gap-1">
          {WINDOWS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setWindow(option.id)}
              aria-pressed={window === option.id}
              className={`rounded border px-2 py-1 text-sm ${
                window === option.id ? "border-accent bg-accent/10 font-medium" : "border-border"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      <ErrorMessage
        error={pulse.error ?? challenges.error ?? players.error ?? progression.error}
      />

      {/* Band 1 */}
      <section className="mt-6 grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {pulse.data ? (
          <>
            <Stat
              label="Solves / hr"
              value={pulse.data.solves_per_hour}
              change={pulse.data.solves - pulse.data.solves_previous}
            />
            <Stat
              label="Attempts per solve"
              value={pulse.data.attempts_per_solve}
              hint="The best early warning — it climbs before solves fall"
            />
            <Stat label="Active players" value={pulse.data.active_players} />
            <Stat
              label="Participation"
              value={`${Math.round(pulse.data.participation * 100)}%`}
              hint={`of ${pulse.data.approved_players} approved`}
            />
            <Stat label="Hints unlocked" value={pulse.data.hints_unlocked} />
            <Stat label="First-time solvers" value={pulse.data.first_time_solvers} />
          </>
        ) : (
          <Spinner />
        )}
      </section>

      {/* Band 2 */}
      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Challenges drifting
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          Ranked by concern. A high near-miss rate with a high ratio means the answer rule is
          wrong, not the challenge.
        </p>
        {challenges.data ? (
          <ChallengeTable rows={challenges.data.challenges.slice(0, 25)} />
        ) : (
          <Spinner />
        )}
      </section>

      {/* Band 3 */}
      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Players stalled
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          {/* Spec 050 §10.2: "stalled" is about the recent past, so a
              whole-event window would make these meaningless. */}
          Uses its own thresholds — the window above does not apply here.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {PLAYER_FILTERS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setPlayerFilter(option.id)}
              aria-pressed={playerFilter === option.id}
              title={option.hint}
              className={`rounded border px-3 py-1 text-sm ${
                playerFilter === option.id
                  ? "border-accent bg-accent/10 font-medium"
                  : "border-border"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        {players.data ? <PlayerTable rows={players.data.players} /> : <Spinner />}
      </section>

      {/* Band 4 */}
      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Progression &amp; economy
        </h2>
        {progression.data ? (
          <div className="mt-3 grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="text-xs font-medium text-content-muted">Zone spread</h3>
              <Bars
                rows={progression.data.zone_spread.map((row) => ({
                  label: row.zone,
                  value: row.players,
                }))}
              />
            </div>
            <div>
              <h3 className="text-xs font-medium text-content-muted">Levels</h3>
              <Bars
                rows={progression.data.levels.map((row) => ({
                  label: `Level ${row.level}`,
                  value: row.players,
                }))}
              />
            </div>
            <div>
              <h3 className="text-xs font-medium text-content-muted">
                Zone difficulty (attempts per solve)
              </h3>
              <Bars
                rows={progression.data.category_health
                  .slice()
                  .sort((a, b) => b.attempts_per_solve - a.attempts_per_solve)
                  .map((row) => ({ label: row.zone, value: row.attempts_per_solve }))}
              />
            </div>
            <div>
              <h3 className="text-xs font-medium text-content-muted">Hint economy</h3>
              <p className="mt-2 text-sm">
                {progression.data.hints.unlocked} hints unlocked by{" "}
                {progression.data.hints.players_using} players ·{" "}
                {progression.data.hints.hints_per_solve} per solve
              </p>
              <p className="mt-1 text-xs text-content-muted">
                Hints cost points, so an unused hint system and an over-used one are both
                problems.
              </p>
            </div>
          </div>
        ) : (
          <Spinner />
        )}
      </section>
    </main>
  );
}

function Stat({
  label,
  value,
  change,
  hint,
}: {
  label: string;
  value: number | string;
  change?: number;
  hint?: string;
}) {
  return (
    <div className="rounded border border-border bg-surface-raised p-3">
      <p className="text-xs text-content-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {/* A rate without a direction is not actionable. */}
      {change !== undefined && change !== 0 && (
        <p className={`text-xs ${change > 0 ? "text-success" : "text-warning"}`}>
          {change > 0 ? "+" : ""}
          {change} vs previous
        </p>
      )}
      {hint && <p className="mt-1 text-xs text-content-faint">{hint}</p>}
    </div>
  );
}

function ChallengeTable({ rows }: { rows: ChallengeMetric[] }) {
  if (rows.length === 0) return <p className="mt-3 text-content-muted">Nothing to report.</p>;

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-content-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">Challenge</th>
            <th className="py-2 pr-3 font-medium">Zone</th>
            <th className="py-2 pr-3 font-medium">Difficulty</th>
            <th className="py-2 pr-3 text-right font-medium">Attempts</th>
            <th className="py-2 pr-3 text-right font-medium">Solves</th>
            <th className="py-2 pr-3 text-right font-medium">Per solve</th>
            <th className="py-2 pr-3 text-right font-medium">vs band</th>
            <th className="py-2 text-right font-medium">Near miss</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.challenge_id} className="border-b border-border">
              <td className="py-2 pr-3">{row.title}</td>
              <td className="py-2 pr-3 text-content-muted">{row.zone ?? "—"}</td>
              <td className="py-2 pr-3 text-content-muted">{row.difficulty}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{row.attempts}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{row.solves}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{row.attempts_per_solve}</td>
              <td className="py-2 pr-3 text-right tabular-nums">
                {row.vs_difficulty === null ? (
                  // Below the attempt floor a multiple would be a lie.
                  <span className="text-content-faint" title="Not enough attempts to compare">
                    —
                  </span>
                ) : (
                  <span className={row.vs_difficulty > 1.5 ? "text-warning" : ""}>
                    {row.vs_difficulty}×
                  </span>
                )}
              </td>
              <td className="py-2 text-right tabular-nums">
                <span className={row.near_miss_rate > 0.2 ? "text-warning" : ""}>
                  {Math.round(row.near_miss_rate * 100)}%
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlayerTable({ rows }: { rows: StalledPlayer[] }) {
  if (rows.length === 0) return <p className="mt-3 text-content-muted">Nobody in that state.</p>;

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-content-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">Player</th>
            <th className="py-2 pr-3 text-right font-medium">Solves</th>
            <th className="py-2 pr-3 text-right font-medium">Level</th>
            <th className="py-2 pr-3 font-medium">Last solve</th>
            <th className="py-2 pr-3 font-medium">Last attempt</th>
            <th className="py-2 pr-3 font-medium">Current wall</th>
            <th className="py-2 text-right font-medium">Hints</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.user_id} className="border-b border-border">
              <td className="py-2 pr-3">{row.display_name}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{row.solves}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{row.level}</td>
              <td className="py-2 pr-3 text-content-muted">{ago(row.last_solve_at)}</td>
              <td className="py-2 pr-3 text-content-muted">{ago(row.last_submission_at)}</td>
              {/* The single most useful field on the page. */}
              <td className="py-2 pr-3">{row.current_wall ?? "—"}</td>
              <td className="py-2 text-right tabular-nums">
                {/* A stuck player with zero hints is a different conversation. */}
                <span className={row.hints_used === 0 ? "text-content-faint" : ""}>
                  {row.hints_used}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((row) => row.value));

  return (
    <ul className="mt-2 flex flex-col gap-1">
      {rows.map((row) => (
        <li key={row.label} className="flex items-center gap-2 text-sm">
          <span className="w-40 shrink-0 truncate text-content-muted">{row.label}</span>
          <span className="h-3 flex-1 rounded bg-surface-sunken">
            <span
              className="block h-3 rounded bg-accent"
              style={{ width: `${(row.value / max) * 100}%` }}
            />
          </span>
          {/* The number is always present, so nothing is carried by bar length
              alone. */}
          <span className="w-12 shrink-0 text-right tabular-nums">{row.value}</span>
        </li>
      ))}
    </ul>
  );
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hr`;
  return `${Math.round(hours / 24)} days`;
}
