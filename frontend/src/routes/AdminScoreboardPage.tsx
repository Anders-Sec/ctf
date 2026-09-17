import { useQuery } from "@tanstack/react-query";

import {
  getAdminBoard,
  type AdminPlayerRow,
  type AdminTeamRow,
  type UnrankedRow,
} from "../api/adminScoreboard";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * The staff board (spec 051 §3).
 *
 * The public board is good and this does not replace it. This is the version
 * for settling a question, and it differs in four ways: the tie-break timestamp
 * is visible, manual adjustments are broken out, accounts kept off the public
 * board are shown, and it is readable whether or not the event is running —
 * which is precisely when placements get settled.
 */

/** A poll, not a socket. One admin settling a placement does not need sub-second
 *  updates, and a second socket subscriber class is a second thing to get wrong. */
const REFRESH_MS = 15_000;

export default function AdminScoreboardPage() {
  const board = useQuery({
    queryKey: ["admin", "scoreboard"],
    queryFn: getAdminBoard,
    refetchInterval: REFRESH_MS,
  });

  if (board.isPending) return <Spinner label="Counting…" />;
  if (board.isError) return <ErrorMessage error={board.error} />;

  const { players, teams, unranked, generated_at } = board.data;

  return (
    <main className="p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Scoreboard</h1>
          <p className="mt-2 text-sm text-content-muted">
            The standings with their workings — tie-breaks, manual adjustments, and anyone the
            public board leaves out.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-content-muted">
            {new Date(generated_at).toLocaleTimeString()}
          </span>
          <button
            type="button"
            onClick={() => downloadCsv(players, teams)}
            className="rounded border border-border px-3 py-1 text-sm hover:bg-surface-sunken"
          >
            Export CSV
          </button>
        </div>
      </header>

      <div className="mt-8 grid gap-8 xl:grid-cols-2">
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
            Players
          </h2>
          <Board rows={players} nameOf={(row) => row.display_name} extra="Party" />
        </section>

        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
            Parties
          </h2>
          <Board rows={teams} nameOf={(row) => row.name} extra="Members" />
        </section>
      </div>

      {unranked.length > 0 && <Unranked rows={unranked} />}
    </main>
  );
}

function Board<T extends AdminPlayerRow | AdminTeamRow>({
  rows,
  nameOf,
  extra,
}: {
  rows: T[];
  nameOf: (row: T) => string;
  extra: string;
}) {
  if (rows.length === 0) {
    return <p className="mt-3 text-content-muted">Nobody has scored yet.</p>;
  }

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-content-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-2 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Name</th>
            <th className="py-2 pr-3 font-medium">{extra}</th>
            <th className="py-2 pr-3 text-right font-medium">Solves</th>
            <th className="py-2 pr-3 text-right font-medium">Solve pts</th>
            <th className="py-2 pr-3 text-right font-medium">Adjusted</th>
            <th className="py-2 pr-3 text-right font-medium">Total</th>
            <th className="py-2 font-medium">Last gain</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = "user_id" in row ? row.user_id : row.team_id;
            const secondary =
              "team_name" in row ? (row.team_name ?? "—") : String(row.member_count);
            return (
              <tr key={key} className="border-b border-border">
                <td className="py-2 pr-2 tabular-nums text-content-muted">{row.rank}</td>
                <td className="py-2 pr-3">{nameOf(row)}</td>
                <td className="py-2 pr-3 text-content-muted">{secondary}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{row.solve_count}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{row.solve_points}</td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {/* Deliberately invisible on the public board. This is the
                      answer when someone asks why a score looks wrong. */}
                  {row.adjustment_points === 0 ? (
                    <span className="text-content-faint">—</span>
                  ) : (
                    <span className={row.adjustment_points > 0 ? "text-success" : "text-danger"}>
                      {row.adjustment_points > 0 ? "+" : ""}
                      {row.adjustment_points}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3 text-right font-medium tabular-nums">{row.score}</td>
                {/* The timestamp that decided a tie, shown rather than trusted. */}
                <td className="py-2 tabular-nums text-content-muted">
                  {row.last_gain_at ? new Date(row.last_gain_at).toLocaleString() : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Unranked({ rows }: { rows: UnrankedRow[] }) {
  return (
    <section className="mt-10 border-t border-border pt-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
        Scored but not ranked
      </h2>
      <p className="mt-1 text-sm text-content-muted">
        Kept off the board, so everyone below them moved up. Listed separately rather than given
        ranks, which would make this page disagree with the public board about every position
        under them.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-content-muted">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Name</th>
              <th className="py-2 pr-3 font-medium">Why</th>
              <th className="py-2 pr-3 text-right font-medium">Solve pts</th>
              <th className="py-2 pr-3 text-right font-medium">Adjusted</th>
              <th className="py-2 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.user_id} className="border-b border-border">
                <td className="py-2 pr-3">{row.display_name}</td>
                <td className="py-2 pr-3">
                  <span className="rounded border border-border px-1.5 py-0.5 text-xs uppercase tracking-wide text-content-muted">
                    {row.reason}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{row.solve_points}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{row.adjustment_points}</td>
                <td className="py-2 text-right font-medium tabular-nums">{row.score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * The standings as they are right now, for the awards conversation.
 *
 * The full event export is spec 056; this is the more frequent need and it is
 * one click.
 */
function downloadCsv(players: AdminPlayerRow[], teams: AdminTeamRow[]): void {
  const rows: string[][] = [
    ["board", "rank", "name", "secondary", "solves", "solve_points", "adjustment_points", "total", "last_gain_at"],
    ...players.map((row) => [
      "player",
      String(row.rank),
      row.display_name,
      row.team_name ?? "",
      String(row.solve_count),
      String(row.solve_points),
      String(row.adjustment_points),
      String(row.score),
      row.last_gain_at ?? "",
    ]),
    ...teams.map((row) => [
      "party",
      String(row.rank),
      row.name,
      String(row.member_count),
      String(row.solve_count),
      String(row.solve_points),
      String(row.adjustment_points),
      String(row.score),
      row.last_gain_at ?? "",
    ]),
  ];

  const escape = (cell: string) => (/[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell);
  // A BOM, because this is opened in Excel and without it every non-ASCII
  // display name arrives mangled.
  const csv = "﻿" + rows.map((row) => row.map(escape).join(",")).join("\r\n");

  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `scoreboard-${new Date().toISOString().slice(0, 16).replace(":", "")}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
