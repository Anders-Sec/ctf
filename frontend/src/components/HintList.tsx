import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { unlockHint, type Hint } from "../api/challenges";
import ErrorMessage from "./ErrorMessage";

/**
 * Hints, with the cost stated before anything is spent.
 *
 * Buying one is irreversible and costs points, so it takes two clicks: the
 * second one names the price. A one-click purchase next to a "submit answer"
 * button is a misclick waiting to happen.
 */
export default function HintList({
  challengeId,
  hints,
}: {
  challengeId: string;
  hints: Hint[];
}) {
  if (hints.length === 0) return null;

  return (
    <section className="mt-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Hints</h2>
      <ul className="mt-3 flex flex-col gap-2">
        {hints.map((hint) => (
          <HintRow key={hint.id} challengeId={challengeId} hint={hint} />
        ))}
      </ul>
    </section>
  );
}

function HintRow({ challengeId, hint }: { challengeId: string; hint: Hint }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const unlock = useMutation({
    mutationFn: () => unlockHint(challengeId, hint.id),
    onSuccess: async () => {
      setConfirming(false);
      // The cost moves the score, and the board shows it.
      await queryClient.invalidateQueries({ queryKey: ["challenge", challengeId] });
      await queryClient.invalidateQueries({ queryKey: ["my-score"] });
    },
  });

  const body = hint.unlocked ? hint.body : unlock.data?.body;

  return (
    <li className="rounded-lg border border-stone bg-white/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{hint.title}</span>

        {body ? (
          <span className="text-sm text-muted">unlocked</span>
        ) : !hint.available ? (
          <span className="text-sm text-muted">locked</span>
        ) : confirming ? (
          <span className="flex items-center gap-2">
            <button
              onClick={() => unlock.mutate()}
              disabled={unlock.isPending}
              className="rounded bg-torch px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {unlock.isPending
                ? "Unlocking…"
                : hint.cost === 0
                  ? "Reveal (free)"
                  : `Spend ${hint.cost} points`}
            </button>
            <button onClick={() => setConfirming(false)} className="text-sm underline">
              Cancel
            </button>
          </span>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="rounded border border-ink px-3 py-1.5 text-sm"
          >
            {hint.cost === 0 ? "Reveal — free" : `Unlock — ${hint.cost} points`}
          </button>
        )}
      </div>

      {!hint.available && !body && (
        <p className="mt-2 text-sm text-muted">
          Unlock the hint before this one, or wait for it to open.
        </p>
      )}

      {hint.cost === 0 && !body && hint.available && (
        <p className="mt-2 text-sm text-muted">
          Free — you have already solved this challenge.
        </p>
      )}

      {body && <p className="mt-3 whitespace-pre-wrap">{body}</p>}
      <ErrorMessage error={unlock.error} />
    </li>
  );
}
