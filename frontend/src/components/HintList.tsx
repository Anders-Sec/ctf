import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { unlockHint, type Hint } from "../api/challenges";
import ErrorMessage from "./ErrorMessage";

/**
 * Hints, with the cost stated before anything is spent.
 *
 * Buying one is irreversible and costs XP, so it takes two clicks: the
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
  const [open, setOpen] = useState(false);

  if (hints.length === 0) return null;

  const unlocked = hints.filter((hint) => hint.unlocked).length;

  return (
    <section className="mt-5 rounded border border-border">
      {/* One line until asked for (spec 062 §5.1). Hints used to render as a
          full section below the body and were routinely taller than it — the
          description is what a player came to read. */}
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm"
      >
        <span aria-hidden className="w-3 text-content-muted">
          {open ? "▾" : "▸"}
        </span>
        <span className="font-medium">Hints</span>
        <span className="text-content-muted">
          {hints.length} available
          {/* "opened", not "unlocked": every button inside this one is an
              "Unlock — 50 XP", and two controls a word apart is ambiguous to
              read out. It also stays true once the challenge is solved and
              hints cost nothing. */}
          {unlocked > 0 && ` · ${unlocked} opened`}
        </span>
      </button>
      {open && (
        <ul className="flex flex-col gap-2 border-t border-border p-3">
          {hints.map((hint) => (
            <HintRow key={hint.id} challengeId={challengeId} hint={hint} />
          ))}
        </ul>
      )}
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
    <li className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{hint.title}</span>

        {body ? (
          <span className="text-sm text-content-muted">unlocked</span>
        ) : !hint.available ? (
          <span className="text-sm text-content-muted">locked</span>
        ) : confirming ? (
          <span className="flex items-center gap-2">
            <button
              onClick={() => unlock.mutate()}
              disabled={unlock.isPending}
              className="rounded bg-accent px-3 py-1.5 text-sm text-on-fill disabled:opacity-50"
            >
              {unlock.isPending
                ? "Unlocking…"
                : hint.cost === 0
                  ? "Reveal (free)"
                  : `Spend ${hint.cost} XP`}
            </button>
            <button onClick={() => setConfirming(false)} className="text-sm underline">
              Cancel
            </button>
          </span>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="rounded border border-content px-3 py-1.5 text-sm"
          >
            {hint.cost === 0 ? "Reveal — free" : `Unlock — ${hint.cost} XP`}
          </button>
        )}
      </div>

      {!hint.available && !body && (
        <p className="mt-2 text-sm text-content-muted">
          Unlock the hint before this one, or wait for it to open.
        </p>
      )}

      {hint.cost === 0 && !body && hint.available && (
        <p className="mt-2 text-sm text-content-muted">
          Free — you have already solved this challenge.
        </p>
      )}

      {body && <p className="mt-3 whitespace-pre-wrap">{body}</p>}
      <ErrorMessage error={unlock.error} />
    </li>
  );
}
