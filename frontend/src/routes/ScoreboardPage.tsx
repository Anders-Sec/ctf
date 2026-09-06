import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getPlayerBoard, getTeamBoard, type PlayerEntry, type TeamEntry } from "../api/scoreboard";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import { useLiveScoreboard } from "../hooks/useLiveScoreboard";

type Tab = "teams" | "players";

export default function ScoreboardPage() {
  const { me } = useSession();
  const [tab, setTab] = useState<Tab>("teams");
  const { boards, status } = useLiveScoreboard();

  // The socket is the live path; these are the fallback for the moment before
  // it connects, and for when it cannot.
  const players = useQuery({
    queryKey: ["scoreboard", "players"],
    queryFn: getPlayerBoard,
    enabled: boards === null,
  });
  const teams = useQuery({
    queryKey: ["scoreboard", "teams"],
    queryFn: getTeamBoard,
    enabled: boards === null,
  });

  const playerRows = boards?.players ?? players.data?.entries ?? [];
  const teamRows = boards?.teams ?? teams.data?.entries ?? [];
  const loading = boards === null && (players.isPending || teams.isPending);
  const error = players.error ?? teams.error;

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Scoreboard</h1>
        <LiveBadge status={status} />
      </header>

      <p className="mt-2 text-sm text-muted">
        A party scores each challenge once, however many members solved it — so a party of
        one and a party of eight can reach the same total.
      </p>

      <div className="mt-5 flex gap-2" role="tablist">
        {(
          [
            ["teams", "Parties"],
            ["players", "Players"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={`rounded px-4 py-2 text-sm font-medium ${
              tab === value ? "bg-ink text-parchment" : "border border-stone"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <ErrorMessage error={error} />

      {loading ? (
        <Spinner label="Reading the ledger…" />
      ) : tab === "teams" ? (
        <TeamTable rows={teamRows} highlightTeamId={me?.team?.id ?? null} />
      ) : (
        <PlayerTable rows={playerRows} highlightUserId={me?.user.id ?? null} />
      )}
    </main>
  );
}

function LiveBadge({ status }: { status: "connecting" | "live" | "offline" }) {
  const label = { connecting: "connecting…", live: "live", offline: "reconnecting…" }[status];
  return (
    <span className="flex items-center gap-2 text-sm text-muted" role="status">
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 rounded-full ${
          status === "live" ? "bg-ink" : "bg-muted"
        } ${status === "live" ? "" : "animate-pulse"}`}
      />
      {label}
    </span>
  );
}

function TeamTable({
  rows,
  highlightTeamId,
}: {
  rows: TeamEntry[];
  highlightTeamId: string | null;
}) {
  if (rows.length === 0) {
    return <p className="mt-8 text-muted">No parties have scored yet.</p>;
  }

  return (
    <table className="mt-4 w-full text-left">
      <thead className="text-sm text-muted">
        <tr>
          <th className="w-12 py-2">#</th>
          <th className="py-2">Party</th>
          <th className="py-2 text-right">Solved</th>
          <th className="py-2 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.team_id}
            className={`border-t border-stone ${
              row.team_id === highlightTeamId ? "bg-ink/5 font-medium" : ""
            }`}
          >
            <td className="py-2">{row.rank}</td>
            <td className="py-2">
              {row.name}
              <span className="ml-2 text-sm text-muted">
                {row.member_count} {row.member_count === 1 ? "adventurer" : "adventurers"}
              </span>
            </td>
            <td className="py-2 text-right">{row.solve_count}</td>
            <td className="py-2 text-right tabular-nums">{row.score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PlayerTable({
  rows,
  highlightUserId,
}: {
  rows: PlayerEntry[];
  highlightUserId: string | null;
}) {
  if (rows.length === 0) {
    return <p className="mt-8 text-muted">Nobody has scored yet.</p>;
  }

  return (
    <table className="mt-4 w-full text-left">
      <thead className="text-sm text-muted">
        <tr>
          <th className="w-12 py-2">#</th>
          <th className="py-2">Player</th>
          <th className="py-2">Party</th>
          <th className="py-2 text-right">Solved</th>
          <th className="py-2 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.user_id}
            className={`border-t border-stone ${
              row.user_id === highlightUserId ? "bg-ink/5 font-medium" : ""
            }`}
          >
            <td className="py-2">{row.rank}</td>
            <td className="py-2">
              <span className="flex items-center gap-2">
                <Avatar
                  userId={row.user_id}
                  displayName={row.display_name}
                  hasAvatar={row.has_avatar}
                  size={24}
                />
                {row.display_name}
              </span>
            </td>
            <td className="py-2 text-muted">{row.team_name ?? "—"}</td>
            <td className="py-2 text-right">{row.solve_count}</td>
            <td className="py-2 text-right tabular-nums">{row.score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
