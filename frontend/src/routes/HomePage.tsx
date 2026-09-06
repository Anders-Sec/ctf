import { Link } from "react-router-dom";

import { useSession } from "../auth/session";
import Spinner from "../components/Spinner";

/**
 * The landing screen, which doubles as the gate. Which state a player sees is
 * decided by `capabilities` from the server, never by a client-side clock —
 * 200 browsers with 200 slightly wrong clocks would otherwise disagree about
 * whether the dungeon is open.
 */
export default function HomePage() {
  const { me, isLoading } = useSession();

  if (isLoading || !me) return <Spinner />;

  const { capabilities, event, user, team } = me;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">
          {event?.name ?? "The dungeon"}
        </h1>
        <p className="mt-2 text-muted">Welcome, {user.display_name}.</p>
      </header>

      {capabilities.blocked_reason === "account_pending_approval" && (
        <GateCard title="Awaiting approval">
          <p>
            A dungeon master needs to let you in before you can play. You can still form or
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

      {capabilities.play && (
        <GateCard title="The dungeon is open">
          <p>
            <Link to="/challenges" className="underline">
              Take on a challenge
            </Link>{" "}
            and start scoring, or see where you stand on the{" "}
            <Link to="/scoreboard" className="underline">
              scoreboard
            </Link>
            .
          </p>
        </GateCard>
      )}

      <section className="rounded-lg border border-stone bg-white/60 p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Your party</h2>
        {team ? (
          <p className="mt-2">
            You march with <Link to="/party" className="underline">{team.name}</Link>
            {team.is_leader && " — and you lead it"}.
          </p>
        ) : (
          <p className="mt-2">
            You have no party yet.{" "}
            <Link to="/party" className="underline">
              Find one
            </Link>
            .
          </p>
        )}
      </section>
    </main>
  );
}

function GateCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-stone bg-white/60 p-6">
      <h2 className="font-medium">{title}</h2>
      <div className="mt-2 text-muted">{children}</div>
    </section>
  );
}
