import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getMyCharacter } from "../api/character";
import { getMyScore, listChallenges, type ChallengeListItem } from "../api/challenges";
import { getMyStanding } from "../api/scoreboard";
import { useSession } from "../auth/session";
import EventCountdown from "../components/EventCountdown";
import FirstSteps, { buildSteps } from "../components/FirstSteps";
import Spinner from "../components/Spinner";
import Tour from "../components/Tour";

/**
 * The landing screen (specs 017, 066).
 *
 * Which gate a player sees is decided by `capabilities` from the server, never
 * by a client-side clock — 200 browsers with 200 slightly wrong clocks would
 * otherwise disagree about whether the dungeon is open. The countdown follows
 * the same rule by offsetting against `server_time`.
 *
 * Beyond the gate it answers the two questions somebody actually arrives with:
 * *how am I doing* and *what do I do next*.
 */
export default function HomePage() {
  const { me, isLoading } = useSession();
  const canPlay = Boolean(me?.capabilities.play);

  const challenges = useQuery({
    queryKey: ["challenges"],
    queryFn: listChallenges,
    enabled: canPlay,
  });
  const score = useQuery({ queryKey: ["my-score"], queryFn: getMyScore, enabled: canPlay });
  const standing = useQuery({
    queryKey: ["scoreboard", "me"],
    queryFn: getMyStanding,
    enabled: canPlay,
  });
  const sheet = useQuery({
    queryKey: ["character", "me"],
    queryFn: getMyCharacter,
    enabled: canPlay,
  });

  if (isLoading || !me) return <Spinner />;

  const { capabilities, event, user, team } = me;
  const rows = challenges.data ?? [];
  const left = whereYouLeftOff(rows, score.data?.solves ?? []);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">
          {event?.name ?? "The dungeon"}
        </h1>
        <p className="mt-1 text-content-muted">Welcome, {user.display_name}.</p>
        <div className="mt-1">
          <EventCountdown event={event} />
        </div>
      </header>

      {capabilities.blocked_reason === "account_pending_approval" && (
        <GateCard title="Awaiting approval">
          <p>
            An organiser needs to let you in before you can play. You can still form or
            join a party in the meantime.
          </p>
        </GateCard>
      )}

      {capabilities.blocked_reason === "account_disabled" && (
        <GateCard title="Your account is disabled">
          <p>Speak to an event organiser if you think this is a mistake.</p>
        </GateCard>
      )}

      {capabilities.blocked_reason === "event_not_started" && (
        <GateCard title="The doors are still shut">
          <p>
            {event?.starts_at
              ? `The crawl begins ${new Date(event.starts_at).toLocaleString()}.`
              : "The start time has not been announced yet."}
          </p>
        </GateCard>
      )}

      {capabilities.blocked_reason === "event_ended" && (
        <GateCard title="The crawl is over">
          <p>Thanks for playing. The scoreboard stands as its final record.</p>
        </GateCard>
      )}

      {canPlay && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card title="Where you left off">
              {left ? (
                <>
                  <p className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{left.zone.name}</span>
                    <span className="text-sm text-content-muted tabular-nums">
                      {left.cleared}/{left.total}
                    </span>
                  </p>
                  {left.next ? (
                    <p className="mt-2 text-sm">
                      Next:{" "}
                      <Link to={`/challenges/${left.next.id}`} className="underline">
                        {left.next.title}
                      </Link>
                      <span className="ml-2 text-content-muted tabular-nums">
                        {left.next.value}
                      </span>
                    </p>
                  ) : (
                    <p className="mt-2 text-sm text-content-muted">
                      Cleared. <Link to="/challenges" className="underline">Pick a new zone</Link>.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-content-muted">
                  Nothing yet.{" "}
                  <Link to="/challenges" className="underline">
                    Open the board
                  </Link>
                  .
                </p>
              )}
            </Card>

            <Card title="Your standing">
              {/* No XP: level is the public shape of the same fact (spec 059). */}
              <dl className="grid grid-cols-3 gap-2 text-center">
                <Stat
                  label="Rank"
                  value={standing.data?.rank == null ? "—" : `#${standing.data.rank}`}
                  of={standing.data?.player_count}
                />
                <Stat label="Level" value={String(me.level)} />
                <Stat
                  label="Party"
                  value={
                    standing.data?.team_rank == null ? "—" : `#${standing.data.team_rank}`
                  }
                  of={standing.data?.team_count}
                />
              </dl>
              <p className="mt-2 text-sm text-content-muted">
                {team ? (
                  <>
                    You march with{" "}
                    <Link to="/party" className="underline">
                      {team.name}
                    </Link>
                    {team.is_leader && " — and you lead it"}.
                  </>
                ) : (
                  <>
                    No party yet.{" "}
                    <Link to="/party" className="underline">
                      Find one
                    </Link>
                    .
                  </>
                )}
              </p>
            </Card>
          </div>

          <FirstSteps
            steps={buildSteps(me, sheet.data, rows, left?.zone ?? firstOpenZone(rows))}
          />
        </>
      )}

      <Tour />
    </main>
  );
}

interface LeftOff {
  zone: { name: string; slug: string };
  cleared: number;
  total: number;
  next: ChallengeListItem | null;
}

/**
 * The zone of the most recent solve, and the first unsolved challenge in it.
 *
 * Derived rather than stored: a "current zone" column on the server would be a
 * second source of truth that could disagree with the board. The board's own
 * order is the server's since spec 062, so "the next one" here is the same row
 * the board would show first.
 */
export function whereYouLeftOff(
  rows: ChallengeListItem[],
  solves: { category: string; solved_at: string }[],
): LeftOff | null {
  if (rows.length === 0 || solves.length === 0) return null;

  const latest = [...solves].sort(
    (a, b) => Date.parse(b.solved_at) - Date.parse(a.solved_at),
  )[0];
  if (!latest) return null;

  const inZone = rows.filter((row) => row.category.name === latest.category);
  if (inZone.length === 0) return null;

  return {
    zone: { name: latest.category, slug: inZone[0]!.category.slug },
    cleared: inZone.filter((row) => row.solved).length,
    total: inZone.length,
    next: inZone.find((row) => !row.solved && !row.locked) ?? null,
  };
}

/** Before the first solve, the checklist points here instead. */
export function firstOpenZone(
  rows: ChallengeListItem[],
): { name: string; slug: string } | null {
  const open = rows.find((row) => !row.locked && !row.solved);
  return open ? { name: open.category.name, slug: open.category.slug } : null;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border-strong bg-surface-raised p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Stat({ label, value, of }: { label: string; value: string; of?: number }) {
  return (
    <div className="rounded border border-border bg-surface py-1.5">
      <dd className="font-semibold tabular-nums">{value}</dd>
      <dt className="text-xs text-content-muted">
        {label}
        {of !== undefined && value !== "—" && (
          <span className="block tabular-nums">of {of}</span>
        )}
      </dt>
    </div>
  );
}

function GateCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface-raised p-6">
      <h2 className="font-medium">{title}</h2>
      <div className="mt-2 text-content-muted">{children}</div>
    </section>
  );
}
