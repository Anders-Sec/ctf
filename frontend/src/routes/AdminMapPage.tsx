import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";

import { listSkills } from "../api/adminSkills";
import {
  exportLayout,
  getMap,
  getMapGraph,
  importLayout,
  resetMapLayout,
  setZonePosition,
  type MapLayoutFile,
} from "../api/dungeon";
import { useSession } from "../auth/session";
import DungeonMap from "../components/DungeonMap";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import ZoneGatePanel from "../components/ZoneGatePanel";

/** FileReader rather than `file.text()`: the latter is missing in jsdom, and
 *  this is supported everywhere without a shim. */
function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

/**
 * Laying out the dungeon and wiring it up (specs 021, 022, 027).
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

  // Carrying the layout between instances (spec 027). The file keys on slug,
  // because category ids differ per environment.
  const layoutInput = useRef<HTMLInputElement>(null);
  const [layoutNote, setLayoutNote] = useState<string | null>(null);

  const download = useMutation({
    mutationFn: exportLayout,
    onSuccess: (layout) => {
      const blob = new Blob([JSON.stringify(layout, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "map-layout.json";
      link.click();
      URL.revokeObjectURL(url);
    },
  });

  const upload = useMutation({
    mutationFn: (layout: MapLayoutFile) => importLayout(layout),
    onSuccess: (result) => {
      setLayoutNote(
        `Placed ${result.applied} ${result.applied === 1 ? "zone" : "zones"}.` +
          (result.unknown.length
            ? ` Not recognised here: ${result.unknown.join(", ")}.`
            : ""),
      );
      queryClient.invalidateQueries({ queryKey: ["map"] });
    },
  });

  const onLayoutFile = async (file: File) => {
    setLayoutNote(null);
    try {
      upload.mutate(JSON.parse(await readText(file)) as MapLayoutFile);
    } catch {
      setLayoutNote("That file is not readable JSON.");
    }
  };

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
          <p className="mt-1 text-sm text-content-muted">
            Drag a zone to move it, click one to change what opens it. Saves as
            you go; players pick it up on their next load. Drag the floor to pan,
            scroll to zoom.
          </p>
        </div>
        {canWrite && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => download.mutate()}
              disabled={download.isPending}
              className="rounded border border-border px-4 py-2 text-sm disabled:opacity-50"
            >
              Export layout
            </button>
            <button
              onClick={() => layoutInput.current?.click()}
              disabled={upload.isPending}
              className="rounded border border-border px-4 py-2 text-sm disabled:opacity-50"
            >
              {upload.isPending ? "Importing…" : "Import layout"}
            </button>
            <input
              ref={layoutInput}
              type="file"
              accept="application/json,.json"
              aria-label="Layout file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void onLayoutFile(file);
                event.target.value = "";
              }}
            />
            <button
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
              className="rounded border border-border px-4 py-2 text-sm disabled:opacity-50"
            >
              {reset.isPending ? "Resetting…" : "Reset layout"}
            </button>
          </div>
        )}
      </header>

      {!canWrite && (
        <p className="mt-4 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
          Read-only — only admins can change the map.
        </p>
      )}

      {unreachable.size > 0 && (
        <p className="mt-4 rounded border border-warning bg-warning/10 px-3 py-2 text-sm">
          {unreachable.size} {unreachable.size === 1 ? "zone is" : "zones are"}{" "}
          unreachable — no path opens {unreachable.size === 1 ? "it" : "them"}.
        </p>
      )}

      {layoutNote && (
        <p className="mt-4 rounded border border-border bg-surface-raised px-3 py-2 text-sm">
          {layoutNote}
        </p>
      )}

      <ErrorMessage
        error={move.error ?? reset.error ?? graph.error ?? upload.error ?? download.error}
      />

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
