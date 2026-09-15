import { useEffect, useState } from "react";

import type { ConnectionsView, PuzzleState } from "../../api/puzzles";

/**
 * Connections (spec 044 §4.2).
 *
 * Selecting and shuffling are local and free. The only thing that reaches the
 * server is a submitted four, which is the only thing that can cost a mistake.
 */

/** Level 1 is the gentlest group, 4 the trap. Ordered, so the colours read as a
 *  difficulty scale rather than as decoration. */
const LEVEL_STYLE = [
  "bg-amber-200 text-ink",
  "bg-emerald-200 text-ink",
  "bg-sky-200 text-ink",
  "bg-violet-200 text-ink",
];

export default function ConnectionsBoard({
  state,
  onPlay,
  pending,
}: {
  state: PuzzleState;
  onPlay: (members: string[]) => void;
  pending: boolean;
}) {
  const view = state.puzzle as ConnectionsView;
  const [picked, setPicked] = useState<string[]>([]);
  const [order, setOrder] = useState<string[]>(view.tiles);
  const over = state.status === "solved" || state.status === "failed";

  // The server's order is authoritative on arrival; shuffling is local from
  // there. Keyed on the joined tiles so a solved group leaving the pool
  // re-syncs, while a re-render does not undo a shuffle.
  useEffect(() => {
    setOrder((current) => {
      const incoming = new Set(view.tiles);
      const kept = current.filter((tile) => incoming.has(tile));
      const added = view.tiles.filter((tile) => !current.includes(tile));
      return [...kept, ...added];
    });
    setPicked((current) => current.filter((tile) => view.tiles.includes(tile)));
  }, [view.tiles.join("|")]);

  const toggle = (tile: string) => {
    setPicked((current) =>
      current.includes(tile)
        ? current.filter((entry) => entry !== tile)
        : current.length < 4
          ? [...current, tile]
          : current,
    );
  };

  const shuffle = () =>
    setOrder((current) => [...current].sort(() => Math.random() - 0.5));

  const solvedGroups = over && view.groups ? view.groups : view.solved_groups;

  return (
    <div>
      <div className="flex flex-col gap-2">
        {solvedGroups.map((group) => (
          <div
            key={group.name}
            className={`rounded-lg px-3 py-2 text-center ${LEVEL_STYLE[group.level - 1]}`}
          >
            <p className="text-sm font-semibold uppercase tracking-wide">{group.name}</p>
            <p className="text-sm">{group.members.join(" · ")}</p>
          </div>
        ))}
      </div>

      {order.length > 0 && (
        <div className="mt-2 grid grid-cols-4 gap-2">
          {order.map((tile) => {
            const chosen = picked.includes(tile);
            return (
              <button
                key={tile}
                type="button"
                onClick={() => toggle(tile)}
                disabled={over || pending}
                aria-pressed={chosen}
                className={`flex min-h-16 items-center justify-center rounded-lg px-1 py-2 text-center text-xs font-semibold uppercase leading-tight break-words disabled:opacity-60 sm:text-sm ${
                  chosen ? "bg-ink text-parchment" : "bg-stone/30 text-ink hover:bg-stone/50"
                }`}
              >
                {tile}
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted" role="status">
          {over
            ? state.status === "solved"
              ? "Solved."
              : "Out of mistakes."
            : `${view.mistakes_remaining} ${
                view.mistakes_remaining === 1 ? "mistake" : "mistakes"
              } left`}
        </p>

        {!over && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={shuffle}
              className="rounded border border-stone px-3 py-1.5 text-sm"
            >
              Shuffle
            </button>
            <button
              type="button"
              onClick={() => setPicked([])}
              disabled={picked.length === 0}
              className="rounded border border-stone px-3 py-1.5 text-sm disabled:opacity-50"
            >
              Deselect
            </button>
            <button
              type="button"
              onClick={() => onPlay(picked)}
              disabled={picked.length !== 4 || pending}
              className="rounded bg-ink px-4 py-1.5 text-sm font-medium text-parchment disabled:opacity-50"
            >
              {pending ? "Checking…" : "Submit"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
