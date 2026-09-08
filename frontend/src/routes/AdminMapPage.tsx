import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getMap, resetMapLayout, setZonePosition } from "../api/dungeon";
import { useSession } from "../auth/session";
import DungeonMap from "../components/DungeonMap";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Laying out the dungeon (spec 021).
 *
 * The same map component players see, in edit mode — so the layout cannot look
 * one way here and another way to them. Drag a zone and it saves on drop; there
 * is no publish step, because this is a pre-event task and a half-finished
 * layout is not a state worth modelling.
 */
export default function AdminMapPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const map = useQuery({ queryKey: ["map"], queryFn: getMap });

  const move = useMutation({
    mutationFn: (input: { id: string; x: number; y: number }) =>
      setZonePosition(input.id, input.x, input.y),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["map"] }),
  });
  const reset = useMutation({
    mutationFn: resetMapLayout,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["map"] }),
  });

  if (map.isPending) return <Spinner label="Unrolling the map…" />;
  if (map.isError) return <ErrorMessage error={map.error} />;

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Map layout</h1>
          <p className="mt-1 text-sm text-muted">
            Drag a zone to place it. Saves as you drop; players pick it up on
            their next load. Drag the floor to pan, scroll to zoom.
          </p>
        </div>
        {canWrite && (
          <button
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="rounded border border-stone px-4 py-2 text-sm disabled:opacity-50"
          >
            {reset.isPending ? "Resetting…" : "Reset layout"}
          </button>
        )}
      </header>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          Read-only — only admins can move zones.
        </p>
      )}

      <ErrorMessage error={move.error ?? reset.error} />

      <DungeonMap
        data={map.data}
        editable={canWrite}
        onMove={(id, x, y) => move.mutate({ id, x, y })}
      />
    </main>
  );
}
