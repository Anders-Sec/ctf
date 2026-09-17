import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { getPlayerBoard, getTeamBoard, type PlayerEntry, type TeamEntry } from "../api/scoreboard";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import BossStars from "../components/BossStars";
import ErrorMessage from "../components/ErrorMessage";
import PartyPanel from "../components/PartyPanel";
import Spinner from "../components/Spinner";
import { frameBoard, TOP_N } from "../components/boardFraming";
import { RARITY_TEXT } from "../components/classRarity";
import { useLiveScoreboard } from "../hooks/useLiveScoreboard";

/**
 * The most-looked-at screen in the platform (spec 059).
 *
 * **No XP, on either board, at any width.** It still orders them — rank is
 * derived from it exactly as spec 005 computes — the number is simply not
 * published, and the server does not send it. What a player collects is shown
 * instead: rank, boss stars, class, level, and the loot title they are wearing.
 *
 * A party row opens a panel; a player row links through to their character
 * sheet. That asymmetry is deliberate — a party has no page of its own, and
 * duplicating a fraction of the sheet in a panel would be a second thing to
 * keep true.
 */
type Tab = "teams" | "players";

export default function ScoreboardPage() {
  const { me } = useSession();
  const [tab, setTab] = useState<Tab>("teams");
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [openParty, setOpenParty] = useState<string | null>(null);
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

  const term = search.trim().toLowerCase();
  const searching = term.length > 0;

  const matchedTeams = teamRows.filter((row) => row.name.toLowerCase().includes(term));
  const matchedPlayers = playerRows.filter((row) =>
    row.display_name.toLowerCase().includes(term),
  );

  const shown = tab === "teams" ? matchedTeams : matchedPlayers;
  const total = tab === "teams" ? teamRows.length : playerRows.length;

  // Switching tabs resets neither the search nor the expansion on purpose: an
  // admin or a player looking somebody up usually wants both boards for them.
  const switchTab = (next: Tab) => {
    setTab(next);
    setOpenParty(null);
  };

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Scoreboard</h1>
        <LiveBadge status={status} />
      </header>

      <p className="mt-2 text-sm text-content-muted">
        A party claims each challenge once, however many members solved it — so a
        party of one and a party of eight can reach the same standing.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="flex gap-2" role="tablist">
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
              onClick={() => switchTab(value)}
              className={`rounded px-4 py-2 text-sm font-medium ${
                tab === value ? "bg-content text-surface" : "border border-border"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={tab === "teams" ? "Find a party" : "Find a player"}
          aria-label={tab === "teams" ? "Search parties" : "Search players"}
          className="ml-auto min-w-40 rounded border border-border-strong bg-surface-raised px-2 py-1.5 text-sm"
        />
      </div>

      <ErrorMessage error={error} />

      {loading ? (
        <Spinner label="Reading the ledger…" />
      ) : searching && shown.length === 0 ? (
        <p className="mt-8 text-content-muted">
          Nobody by that name {tab === "teams" ? "has a party here" : "is on the board"}.
        </p>
      ) : tab === "teams" ? (
        <TeamBoard
          rows={matchedTeams}
          myTeamId={me?.team?.id ?? null}
          searching={searching}
          showAll={showAll}
          onOpenParty={setOpenParty}
        />
      ) : (
        <PlayerBoard
          rows={matchedPlayers}
          myUserId={me?.user.id ?? null}
          searching={searching}
          showAll={showAll}
          onOpenParty={setOpenParty}
        />
      )}

      {/* Nothing to expand while searching: matches already show in full, with
          their real ranks. */}
      {!loading && !searching && !showAll && shown.length > TOP_N && (
        <p className="mt-5 text-center">
          <button type="button" onClick={() => setShowAll(true)} className="text-sm underline">
            Show all {total}
          </button>
        </p>
      )}
      {!loading && !searching && showAll && (
        <p className="mt-5 text-center">
          <button type="button" onClick={() => setShowAll(false)} className="text-sm underline">
            Show the top {TOP_N}
          </button>
        </p>
      )}

      {openParty && <PartyPanel teamId={openParty} onClose={() => setOpenParty(null)} />}
    </main>
  );
}

function LiveBadge({ status }: { status: "connecting" | "live" | "offline" }) {
  const label = { connecting: "connecting…", live: "live", offline: "reconnecting…" }[status];
  return (
    <span className="flex items-center gap-2 text-sm text-content-muted" role="status">
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 rounded-full ${
          status === "live" ? "bg-content" : "bg-content-muted"
        } ${status === "live" ? "" : "animate-pulse"}`}
      />
      {label}
    </span>
  );
}

/**
 * The break in the list.
 *
 * A real rule with a word on it rather than a gap — it says "the list skips"
 * instead of leaving the reader to infer that from a jump in the rank column.
 */
function Break({ columns }: { columns: number }) {
  return (
    <tr>
      <td colSpan={columns} className="py-1 text-center text-content-faint">
        <span aria-hidden>· · ·</span>
        {/* Said out loud too. A reader who cannot see the rule would otherwise
            have to infer the skip from a jump in the rank column. */}
        <span className="sr-only">Ranks skipped</span>
      </td>
    </tr>
  );
}

function Rank({ value }: { value: number }) {
  return (
    <td className="py-2 text-lg font-semibold tabular-nums text-content-muted">{value}</td>
  );
}

function TeamBoard({
  rows,
  myTeamId,
  searching,
  showAll,
  onOpenParty,
}: {
  rows: TeamEntry[];
  myTeamId: string | null;
  searching: boolean;
  showAll: boolean;
  onOpenParty: (teamId: string) => void;
}) {
  if (rows.length === 0) {
    return <p className="mt-8 text-content-muted">No parties have taken the field yet.</p>;
  }

  const { rows: framed, breakBeforeLast } = frameBoard(rows, {
    isMine: (row) => row.team_id === myTeamId,
    showAll,
    searching,
  });

  return (
    <table className="mt-4 w-full text-left">
      <thead className="text-sm text-content-muted">
        <tr>
          <th className="w-12 py-2">#</th>
          <th className="py-2">Party</th>
          <th className="py-2 text-right">Level</th>
        </tr>
      </thead>
      <tbody>
        {framed.map((row, index) => (
          // The fragment carries the key, because the break and the row are two
          // siblings produced by one iteration.
          <Fragment key={row.team_id}>
            {breakBeforeLast && index === framed.length - 1 && <Break columns={3} />}
            <tr
              className={`border-t border-border ${
                row.team_id === myTeamId ? "bg-accent/10 font-medium" : ""
              }`}
            >
              <Rank value={row.rank} />
              <td className="py-2">
                <span className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenParty(row.team_id)}
                    className="text-left font-medium hover:underline"
                  >
                    {row.name}
                  </button>
                  {/* Beside the name, not in a column of their own: they read as
                      part of the party's identity (spec 059 §2). */}
                  <BossStars stars={row.stars} />
                  {row.team_id === myTeamId && (
                    <span className="text-xs text-accent-strong">you</span>
                  )}
                </span>
                <span className="mt-0.5 block text-xs text-content-muted">
                  {row.member_count} {row.member_count === 1 ? "adventurer" : "adventurers"} ·{" "}
                  {row.solve_count} solved
                </span>
              </td>
              <td className="py-2 text-right text-lg tabular-nums">{row.level}</td>
            </tr>
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function PlayerBoard({
  rows,
  myUserId,
  searching,
  showAll,
  onOpenParty,
}: {
  rows: PlayerEntry[];
  myUserId: string | null;
  searching: boolean;
  showAll: boolean;
  onOpenParty: (teamId: string) => void;
}) {
  if (rows.length === 0) {
    return <p className="mt-8 text-content-muted">Nobody has taken the field yet.</p>;
  }

  const { rows: framed, breakBeforeLast } = frameBoard(rows, {
    isMine: (row) => row.user_id === myUserId,
    showAll,
    searching,
  });

  return (
    <table className="mt-4 w-full text-left">
      <thead className="text-sm text-content-muted">
        <tr>
          <th className="w-12 py-2">#</th>
          <th className="py-2">Player</th>
          <th className="hidden py-2 sm:table-cell">Party</th>
          <th className="py-2 text-right">Level</th>
        </tr>
      </thead>
      <tbody>
        {framed.map((row, index) => (
          <Fragment key={row.user_id}>
            {breakBeforeLast && index === framed.length - 1 && <Break columns={4} />}
            <tr
              className={`border-t border-border ${
                row.user_id === myUserId ? "bg-accent/10 font-medium" : ""
              }`}
            >
              <Rank value={row.rank} />
              <td className="py-2">
                <span className="flex items-start gap-2">
                  <Link to={`/character/${row.user_id}`} className="shrink-0">
                    <Avatar
                      userId={row.user_id}
                      displayName={row.display_name}
                      hasAvatar={row.has_avatar}
                      size={32}
                    />
                  </Link>
                  <span className="min-w-0">
                    <Link
                      to={`/character/${row.user_id}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {row.display_name}
                      {row.user_id === myUserId && (
                        <span className="ml-2 text-xs font-normal text-accent-strong">you</span>
                      )}
                    </Link>
                    {row.title && (
                      // Worn titles are cosmetic by design (038), and this is
                      // the one place anybody else sees them.
                      <span className="block truncate text-xs italic text-content-muted">
                        {row.title}
                      </span>
                    )}
                    <span className="mt-0.5 flex flex-wrap items-center gap-2">
                      {row.class_name && (
                        <span
                          className={`text-xs ${RARITY_TEXT[row.class_rarity ?? ""] ?? "text-content-muted"}`}
                        >
                          {row.class_name}
                        </span>
                      )}
                      {/* Their own kills, never their party's (spec 059 §2). */}
                      <BossStars stars={row.stars} />
                    </span>
                    {/* The party, on narrow screens where its column is gone. */}
                    <span className="mt-0.5 block text-xs text-content-muted sm:hidden">
                      {row.team_name ?? "no party"}
                    </span>
                  </span>
                </span>
              </td>
              <td className="hidden py-2 text-sm text-content-muted sm:table-cell">
                {row.team_id && row.team_name ? (
                  <button
                    type="button"
                    onClick={() => onOpenParty(row.team_id as string)}
                    className="text-left hover:underline"
                  >
                    {row.team_name}
                  </button>
                ) : (
                  "—"
                )}
              </td>
              <td className="py-2 text-right text-lg tabular-nums">{row.level}</td>
            </tr>
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}
