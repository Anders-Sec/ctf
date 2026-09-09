import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  generateSampleData,
  purgeSampleData,
  type SampleDataMode,
} from "../api/sampleData";
import ErrorMessage from "./ErrorMessage";

/**
 * Fill the event with a coherent sample dataset, so the platform can be worked
 * on with data in it. Generating replaces any previous sample data rather than
 * stacking, and the purge takes back exactly what was made.
 *
 * The backend refuses this in production — it invents players, solves and
 * scores, and an accidental click during the real event would be a mess.
 */
export default function SampleDataPanel() {
  const queryClient = useQueryClient();
  const refreshEverything = () => queryClient.invalidateQueries();

  const generate = useMutation({
    mutationFn: (mode: SampleDataMode) => generateSampleData(mode),
    onSuccess: refreshEverything,
  });
  const purge = useMutation({
    mutationFn: purgeSampleData,
    onSuccess: refreshEverything,
  });

  const summary = generate.data;

  return (
    <section className="mt-8 rounded border border-stone bg-white/40 p-4">
      <h2 className="text-lg font-semibold">Sample data</h2>
      <p className="mt-1 text-sm text-muted">
        Two shapes, one purge. <strong>Standalone</strong> builds a
        self-contained four-zone event of its own, for working on the platform in
        isolation. <strong>Fill the dungeon</strong> puts sample challenges into
        the real 22 zones with the real skills attached, so the map, the
        progression gates and the class roster can all be seen working.
        Regenerating replaces the previous set. Not available in production.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={() => generate.mutate("standalone")}
          disabled={generate.isPending || purge.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          {generate.isPending ? "Generating…" : "Generate sample data"}
        </button>
        <button
          onClick={() => generate.mutate("dungeon")}
          disabled={generate.isPending || purge.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          {generate.isPending ? "Generating…" : "Fill the dungeon"}
        </button>
        <button
          onClick={() => purge.mutate()}
          disabled={generate.isPending || purge.isPending}
          className="rounded border border-stone px-4 py-2 text-sm disabled:opacity-50"
        >
          {purge.isPending ? "Removing…" : "Remove sample data"}
        </button>
        {purge.isSuccess && <span className="text-sm text-muted">Removed.</span>}
      </div>

      {summary && (
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Zones", summary.categories],
              ["Challenges", summary.challenges],
              ["Gates", summary.gates],
              ["Skill links", summary.skills],
              ["Hints", summary.hints],
              ["Players", summary.players],
              ["Parties", summary.teams],
              ["Solves", summary.solves],
              ["Achievements", summary.achievements],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt className="text-muted">{label}</dt>
              <dd className="text-lg font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <ErrorMessage error={generate.error ?? purge.error} />
    </section>
  );
}
