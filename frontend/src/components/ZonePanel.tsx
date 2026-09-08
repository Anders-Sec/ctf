import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { listChallenges } from "../api/challenges";
import type { Zone } from "../api/dungeon";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";

/**
 * A zone's challenges, over the map rather than instead of it (spec 019) — the
 * map stays visible behind, so you keep your place in the dungeon.
 *
 * It filters the same challenge list the board uses, so a challenge's locked and
 * solved state here can never disagree with the list view.
 */
export default function ZonePanel({
  zone,
  onClose,
}: {
  zone: Zone;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const challenges = useQuery({ queryKey: ["challenges"], queryFn: listChallenges });

  useEffect(() => {
    // Focus moves in on open and Escape always gets you out — a panel you can
    // tab behind is worse than no panel.
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = (challenges.data ?? []).filter((c) => c.category.id === zone.id);
  const condition = zone.unlock_requirements.map((r) => r.description).join(", ");

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-ink/40"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`${zone.name} challenges`}
        onClick={(event) => event.stopPropagation()}
        className="h-full w-full max-w-md overflow-y-auto bg-parchment p-6 shadow-xl outline-none"
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">{zone.name}</h2>
            <p className="mt-1 text-sm text-muted">
              {zone.cleared} of {zone.total} cleared
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded border border-stone px-3 py-1 text-sm hover:bg-white/60"
          >
            Close
          </button>
        </header>

        {zone.locked && (
          <p className="mt-4 rounded border border-stone bg-white/60 px-3 py-2 text-sm">
            <strong>Sealed.</strong> {condition || "Not yet open."}
          </p>
        )}

        {challenges.isPending && <Spinner label="Reading the room…" />}
        <ErrorMessage error={challenges.error} />

        {!challenges.isPending && rows.length === 0 && (
          <p className="mt-6 text-sm text-muted">Nothing here yet.</p>
        )}

        <ul className="mt-4 space-y-2">
          {rows.map((challenge) => (
            <li
              key={challenge.id}
              className={`rounded border px-4 py-3 ${
                challenge.solved
                  ? "border-ink/40 bg-ink/5"
                  : challenge.locked
                    ? "border-stone bg-white/40 opacity-70"
                    : "border-stone bg-white/60"
              }`}
            >
              {challenge.locked ? (
                // Deliberately not a link: there is nothing behind it yet.
                <div>
                  <span className="font-medium">{challenge.title}</span>
                  <p className="mt-1 text-xs text-muted">
                    {challenge.unlock_requirements
                      .map((r) => r.description)
                      .join(", ") || "Locked"}
                  </p>
                </div>
              ) : (
                <Link
                  to={`/challenges/${challenge.id}`}
                  className="flex items-baseline justify-between gap-3 hover:underline"
                >
                  <span className="font-medium">
                    {challenge.title}
                    {challenge.solved && (
                      <span className="ml-2 text-sm text-muted">✓ cleared</span>
                    )}
                  </span>
                  <span className="text-sm text-muted tabular-nums">
                    {challenge.value} XP
                  </span>
                </Link>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
