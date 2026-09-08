import { useMutation, useQueryClient } from "@tanstack/react-query";

import { generateSampleData, purgeSampleData } from "../api/sampleData";
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
    mutationFn: generateSampleData,
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
        Fills the event with skills, classes, four gated zones of challenges,
        hints, players and solves — enough to see every feature working.
        Regenerating replaces the previous set. Not available in production.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={() => generate.mutate()}
          disabled={generate.isPending || purge.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          {generate.isPending ? "Generating…" : "Generate sample data"}
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
              ["Skills", summary.skills],
              ["Classes", summary.classes],
              ["Hints", summary.hints],
              ["Players", summary.players],
              ["Parties", summary.teams],
              ["Solves", summary.solves],
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
