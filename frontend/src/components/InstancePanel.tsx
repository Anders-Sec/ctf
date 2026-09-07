import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  destroyInstance,
  extendInstance,
  getInstance,
  launchInstance,
  type Instance,
} from "../api/instances";
import { ApiError } from "../api/client";

/**
 * The player's live target for a container-backed challenge.
 *
 * Provisioning is slow (spec 009), so this is poll-based: launch returns
 * `pending`, and the query below re-fetches every couple of seconds until the
 * dungeon master reports it `running` and hands over a link — or `failed`, which
 * is shown rather than spun on forever.
 */
export default function InstancePanel({ challengeId }: { challengeId: string }) {
  const queryClient = useQueryClient();

  const instance = useQuery({
    queryKey: ["instance", challengeId],
    queryFn: () => getInstance(challengeId),
    // A 404 means "you have none", which is an answer, not an error.
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 404) && count < 2,
    // Poll only while something is still being summoned.
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? 2000 : false,
  });

  const current: Instance | null =
    instance.data && instance.data.status !== "destroyed" ? instance.data : null;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["instance", challengeId] });

  const launch = useMutation({ mutationFn: () => launchInstance(challengeId), onSuccess: invalidate });
  const destroy = useMutation({
    mutationFn: () => destroyInstance(challengeId),
    onSuccess: () => queryClient.setQueryData(["instance", challengeId], null),
  });
  const extend = useMutation({ mutationFn: () => extendInstance(challengeId), onSuccess: invalidate });

  const notFound = instance.error instanceof ApiError && instance.error.status === 404;

  return (
    <section className="mt-6 rounded-lg border border-stone bg-white/40 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Live target</h2>

      {(!current || notFound) && (
        <div className="mt-3">
          <p className="text-sm text-muted">
            This encounter has a live target you can summon. It is yours (or your party's)
            alone, and it winds down on a timer.
          </p>
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending}
            className="mt-3 rounded bg-torch px-4 py-2 text-sm text-parchment disabled:opacity-50"
          >
            {launch.isPending ? "Summoning…" : "Summon your dungeon"}
          </button>
          {launch.error instanceof ApiError && (
            <p role="alert" className="mt-2 text-sm text-muted">
              {launch.error.code === "instance_cap_reached"
                ? "You already have as many live targets as you can run at once. Close one first."
                : "The dungeon could not be summoned right now. Try again shortly."}
            </p>
          )}
        </div>
      )}

      {current?.status === "pending" && (
        <p className="mt-3 text-sm text-muted" role="status">
          Summoning your dungeon… this can take a moment.
        </p>
      )}

      {current?.status === "running" && (
        <div className="mt-3 space-y-3">
          <a
            href={current.connection_url ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="inline-block rounded bg-torch px-4 py-2 text-sm text-parchment"
          >
            Enter the dungeon ↗
          </a>
          <p className="text-xs text-muted">{current.connection_url}</p>
          <div className="flex gap-3 text-sm">
            <button onClick={() => extend.mutate()} className="underline">
              Give me more time
            </button>
            <button onClick={() => destroy.mutate()} className="underline text-muted">
              Close it
            </button>
          </div>
        </div>
      )}

      {current?.status === "failed" && (
        <div className="mt-3">
          <p role="alert" className="text-sm text-muted">
            The dungeon collapsed as it formed. Summon it again.
          </p>
          <button
            onClick={() => launch.mutate()}
            className="mt-2 rounded border border-stone px-3 py-1 text-sm"
          >
            Try again
          </button>
        </div>
      )}
    </section>
  );
}
