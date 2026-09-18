import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getMyCharacter } from "../api/character";
import { getAchievements } from "../api/notifications";
import {
  getMyStanding,
  getPlayerBoard,
  getTeamBoard,
  type PlayerEntry,
  type TeamEntry,
} from "../api/scoreboard";
import type { Me } from "../api/auth";
import BossStars from "./BossStars";
import { formatRarity } from "./sheet/AchievementsPanel";

/**
 * The ending (spec 068).
 *
 * Five days of play used to finish with one line of text. This is the payoff,
 * and it is nearly free: `view_scoreboard` stays true after the event ends, so
 * nothing has to be frozen, and every figure below already exists.
 *
 * The personal half matters more than the podium. Eighty-seven people did not
 * win, and the screen should still be worth their time.
 *
 * **XP is shown here.** This is a player's own summary in their own chrome,
 * which is the rule as 064 §7.1 states it: never anybody else's, never on a
 * board.
 */
export default function EventEnding({ me }: { me: Me }) {
  const players = useQuery({ queryKey: ["scoreboard", "players"], queryFn: getPlayerBoard });
  const teams = useQuery({ queryKey: ["scoreboard", "teams"], queryFn: getTeamBoard });
  const standing = useQuery({ queryKey: ["scoreboard", "me"], queryFn: getMyStanding });
  const achievements = useQuery({ queryKey: ["achievements"], queryFn: getAchievements });
  const sheet = useQuery({ queryKey: ["character", "me"], queryFn: getMyCharacter });

  const mine = (players.data?.entries ?? []).find((row) => row.user_id === me.user.id);
  const rarest = achievements.data?.rarest?.[0];

  return (
    <section className="rounded-lg border border-border-strong bg-surface-raised p-5">
      <h2 className="text-2xl font-semibold tracking-tight">The crawl is over</h2>
      <p className="mt-1 text-sm text-content-muted">
        Thanks for playing. The scoreboard stands as its final record.
      </p>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        {/* Three, not ten — the full board is one link away and this is the
            moment, not the record. */}
        <Podium title="Parties" rows={teams.data?.entries ?? []} nameOf={(row) => row.name} />
        <Podium
          title="Players"
          rows={players.data?.entries ?? []}
          nameOf={(row) => row.display_name}
        />
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Your five days
        </h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          <Fact
            label="Rank"
            value={
              standing.data?.rank == null
                ? "unranked"
                : `#${standing.data.rank} of ${standing.data.player_count}`
            }
          />
          <Fact
            label="Party"
            value={
              standing.data?.team_rank == null
                ? me.team?.name ?? "none"
                : `#${standing.data.team_rank} of ${standing.data.team_count}`
            }
          />
          <Fact label="Level" value={String(me.level)} />
          <Fact label="Solved" value={String(mine?.solve_count ?? 0)} />
          <Fact
            label="Achievements"
            value={`${achievements.data?.earned ?? 0} of ${achievements.data?.total ?? 0}`}
          />
          <Fact label="Total XP" value={me.total_xp.toLocaleString()} />
        </dl>

        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-content-muted">Bosses felled</span>
          <BossStars stars={mine?.stars ?? []} size="lg" />
        </p>

        {rarest && (
          <p className="mt-1 text-sm">
            <span className="text-content-muted">Rarest</span>{" "}
            <span className="font-medium">{rarest.name}</span>
            <span className="ml-1 text-content-muted tabular-nums">
              {formatRarity(rarest.rarity)} of players
            </span>
          </p>
        )}

        {sheet.data?.equipped_title && (
          <p className="mt-1 text-sm">
            <span className="text-content-muted">Finished as</span>{" "}
            <span className="italic">{sheet.data.equipped_title}</span>
          </p>
        )}

        <p className="mt-4">
          <Link to="/scoreboard" className="text-sm underline">
            The full scoreboard →
          </Link>
        </p>
      </div>
    </section>
  );
}

/**
 * Ties share a place, exactly as spec 059 §4.1 decided — so a shared third
 * shows as two thirds and there is no fourth. The rows already carry the
 * shared rank; this only has to stop counting.
 */
function Podium<T extends PlayerEntry | TeamEntry>({
  title,
  rows,
  nameOf,
}: {
  title: string;
  rows: T[];
  nameOf: (row: T) => string;
}) {
  const top = rows.filter((row) => row.rank <= 3);

  return (
    <div>
      <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h3>
      {top.length === 0 ? (
        <p className="mt-2 text-sm text-content-muted">Nobody took the field.</p>
      ) : (
        <ol className="mt-2 flex flex-col gap-1">
          {top.map((row) => (
            <li
              key={nameOf(row)}
              className="flex items-baseline justify-between gap-2 text-sm"
            >
              <span className="min-w-0 truncate">
                <span aria-hidden className="mr-1">
                  {["🥇", "🥈", "🥉"][row.rank - 1]}
                </span>
                {nameOf(row)}
              </span>
              <span className="shrink-0 text-content-muted tabular-nums">Lv {row.level}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-content-muted">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}
