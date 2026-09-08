import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { listSkills } from "../api/adminSkills";
import { getMap, getMapGraph, resetMapLayout, setZonePosition } from "../api/dungeon";
import { useSession } from "../auth/session";
import DungeonMap from "../components/DungeonMap";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import ZoneGatePanel from "../components/ZoneGatePanel";

/**
 * Laying out the dungeon and wiring it up (specs 021, 022).
 *
 * The same map component players see, in edit mode — so the layout cannot look
 * one way here and another way to them. Drag a zone to move it, click one to
 * edit what opens it. Both save immediately; there is no publish step, because
 * this is a pre-event task and a half-finished layout is not a state worth
 * modelling.
 */
export default function AdminMapPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);

  const map = useQuery({ queryKey: ["map"], queryFn: getMap });
  const graph = useQuery({ queryKey: ["map-graph"], queryFn: getMapGraph });
  const skills = useQuery({ queryKey: ["admin-skills"], queryFn: listSkills });

  const move = useMutation({
    mutationFn: (input: { id: string; x: number; y: number }) =>
      setZonePosition(input.id, input.x, input.y),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["map"] }),
  });
  const reset = useMutation({
    mutationFn: resetMapLayout,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["map"] }),
  });

  const zones = useMemo(() => graph.data?.zones ?? [], [graph.data]);
  const unreachable = useMemo(
    () => new Set(zones.filter((zone) => !zone.reachable).map((zone) => zone.id)),
    [zones],
  );
  const editing = zones.find((zone) => zone.id === editingZoneId) ?? null;

  const event = me?.event;
  const eventRunning = useMemo(() => {
    if (!event?.starts_at || !event?.ends_at) return false;
    const now = new Date(event.server_time ?? Date.now()).getTime();
    return (
      now >= new Date(event.starts_at).getTime() &&
      now <= new Date(event.ends_at).getTime()
    );
  }, [event]);

  if (map.isPending) return <Spinner label="Unrolling the map…" />;
  if (map.isError) return <ErrorMessage error={map.error} />;

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Map layout</h1>
          <p className="mt-1 text-sm text-muted">
            Drag a zone to move it, click one to change what opens it. Saves as
            you go; players pick it up on their next load. Drag the floor to pan,
            scroll to zoom.
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
          Read-only — only admins can change the map.
        </p>
      )}

      {unreachable.size > 0 && (
        <p className="mt-4 rounded border border-torch bg-torch/10 px-3 py-2 text-sm">
          {unreachable.size} {unreachable.size === 1 ? "zone is" : "zones are"}{" "}
          unreachable — no path opens {unreachable.size === 1 ? "it" : "them"}.
        </p>
      )}

      <ErrorMessage error={move.error ?? reset.error ?? graph.error} />

      <DungeonMap
        data={map.data}
        editable={canWrite}
        onMove={(id, x, y) => move.mutate({ id, x, y })}
        onEditGates={setEditingZoneId}
        unreachable={unreachable}
      />

      {editing && (
        <ZoneGatePanel
          zone={editing}
          zones={zones}
          skills={skills.data ?? []}
          eventRunning={eventRunning}
          onClose={() => setEditingZoneId(null)}
        />
      )}
    </main>
  );
}
