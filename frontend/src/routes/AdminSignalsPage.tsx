import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  dismissSignal,
  getPlayerTimeline,
  getSignals,
  SIGNAL_LABELS,
  type Finding,
} from "../api/signals";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Signals for review.
 *
 * The wording here is doing real work. These are colleagues, and the most
 * likely cause of every finding is two people sitting together talking about a
 * puzzle. The page says "signals", never "violations", shows the innocent
 * explanation beside the evidence, and offers no way to punish anyone — the
 * only action is to dismiss.
 */
export default function AdminSignalsPage() {
  const queryClient = useQueryClient();
  const [inspecting, setInspecting] = useState<string | null>(null);

  const signals = useQuery({ queryKey: ["admin", "signals"], queryFn: getSignals });

  const dismiss = useMutation({
    mutationFn: ({ type, key }: { type: string; key: string }) => dismissSignal(type, key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "signals"] }),
  });

  if (signals.isPending) return <Spinner label="Looking for patterns…" />;
  if (signals.isError) return <ErrorMessage error={signals.error} />;

  const data = signals.data;
  const total = Object.values(data.counts).reduce((sum, count) => sum + count, 0);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Signals</h1>
        <p className="mt-2 text-muted">
          Things worth a second look — <strong>not</strong> accusations. Almost every
          finding here has an innocent explanation, and two colleagues sitting together
          talking about a puzzle will trip several of them. Nothing on this page changes a
          score or an account.
        </p>
      </header>

      {total === 0 ? (
        <p className="mt-8 text-muted">Nothing to review.</p>
      ) : (
        Object.entries(data.findings)
          .filter(([, findings]) => findings.length > 0)
          .map(([type, findings]) => (
            <section key={type} className="mt-8">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
                {SIGNAL_LABELS[type] ?? type} ({findings.length})
              </h2>
              <ul className="mt-3 flex flex-col gap-3">
                {findings.map((finding) => (
                  <FindingCard
                    key={finding.subject_key}
                    finding={finding}
                    onDismiss={() =>
                      dismiss.mutate({ type: finding.signal_type, key: finding.subject_key })
                    }
                    onInspect={setInspecting}
                  />
                ))}
              </ul>
            </section>
          ))
      )}

      <ErrorMessage error={dismiss.error} />

      {inspecting && (
        <PlayerTimeline userId={inspecting} onClose={() => setInspecting(null)} />
      )}
    </main>
  );
}

function FindingCard({
  finding,
  onDismiss,
  onInspect,
}: {
  finding: Finding;
  onDismiss: () => void;
  onInspect: (userId: string) => void;
}) {
  return (
    <li className="rounded-lg border border-stone bg-white/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex-1">
          <p className="font-medium">
            {finding.participants.map((person, index) => (
              <span key={person.user_id}>
                {index > 0 && <span className="text-muted"> and </span>}
                <button
                  onClick={() => onInspect(person.user_id)}
                  className="underline decoration-dotted"
                >
                  {person.display_name}
                </button>
              </span>
            ))}
            {finding.challenge_title && (
              <span className="text-muted"> · {finding.challenge_title}</span>
            )}
          </p>

          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {Object.entries(finding.evidence).map(([key, value]) => (
              <span key={key}>
                <dt className="inline text-muted">{key.replace(/_/g, " ")}: </dt>
                <dd className="inline font-mono">
                  {Array.isArray(value) ? value.join(", ") : String(value)}
                </dd>
              </span>
            ))}
          </dl>

          {/* Beside the evidence, never below the fold. */}
          <p className="mt-2 rounded bg-parchment px-3 py-2 text-sm text-muted">
            <strong className="text-ink">Probably: </strong>
            {finding.innocent_explanation}
          </p>
        </div>

        <button
          onClick={onDismiss}
          className="shrink-0 rounded border border-stone px-3 py-1.5 text-sm"
        >
          Looks fine
        </button>
      </div>
    </li>
  );
}

function PlayerTimeline({ userId, onClose }: { userId: string; onClose: () => void }) {
  const timeline = useQuery({
    queryKey: ["admin", "timeline", userId],
    queryFn: () => getPlayerTimeline(userId),
  });

  return (
    <aside
      className="mt-10 rounded-lg border border-ink/30 bg-white/80 p-5"
      aria-label="Player timeline"
    >
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">
          {timeline.data?.display_name ?? "Player"} — everything they did
        </h2>
        <button onClick={onClose} className="text-sm underline">
          Close
        </button>
      </div>

      {timeline.isPending ? (
        <Spinner />
      ) : timeline.isError ? (
        <ErrorMessage error={timeline.error} />
      ) : timeline.data.events.length === 0 ? (
        <p className="mt-3 text-muted">Nothing recorded for this player yet.</p>
      ) : (
        <ol className="mt-3 flex flex-col gap-1 text-sm">
          {timeline.data.events.map((event, index) => (
            <li key={index} className="flex gap-3 border-t border-stone py-1">
              <span className="w-40 shrink-0 text-muted">
                {new Date(event.at).toLocaleString()}
              </span>
              <span className="w-24 shrink-0">{event.kind.replace(/_/g, " ")}</span>
              <span className="flex-1">
                {event.challenge && <span className="text-muted">{event.challenge} · </span>}
                <span className="font-mono">{event.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
