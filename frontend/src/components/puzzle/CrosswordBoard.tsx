import { useEffect, useMemo, useRef, useState } from "react";

import type { CrosswordView, PuzzleState } from "../../api/puzzles";

/**
 * The crossword mini (spec 044 §4.3).
 *
 * Typing is kept in `localStorage` on every keystroke and flushed to the server
 * on leaving. Split that way because the two have different stakes: losing the
 * letters costs retyping, while losing the *checks used* would hand out three
 * fresh ones for the price of clearing site data. So the letters are local and
 * fast, and checks, wrong-cell marks and whether the session is over come from
 * the server and are never written here.
 */

const BLOCK = "#";

function storageKey(challengeId: string) {
  return `ctf.crossword.${challengeId}`;
}

interface Stored {
  grid: string[][];
  saved_at: number;
}

function readStored(challengeId: string): Stored | null {
  try {
    const raw = localStorage.getItem(storageKey(challengeId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    return Array.isArray(parsed?.grid) ? parsed : null;
  } catch {
    // A private window, blocked site data, or something that is not ours.
    // The server's copy is the fallback and it is always there.
    return null;
  }
}

/** Has this local copy anything the server's has not? */
function isRicher(local: string[][], server: string[][]) {
  const filled = (grid: string[][]) =>
    grid.flat().filter((cell) => cell && cell !== BLOCK).length;
  return filled(local) > filled(server);
}

export default function CrosswordBoard({
  challengeId,
  state,
  onPlay,
  onSave,
  pending,
}: {
  challengeId: string;
  state: PuzzleState;
  onPlay: (grid: string[][]) => void;
  onSave: (grid: string[][]) => void;
  pending: boolean;
}) {
  const view = state.puzzle as CrosswordView;
  const over = state.status === "solved" || state.status === "failed";

  const blocks = useMemo(
    () => new Set(view.blocks.map(([row, col]) => `${row}:${col}`)),
    [view.blocks],
  );
  const numbers = useMemo(
    () => new Map(view.numbers.map((entry) => [`${entry.row}:${entry.col}`, entry.number])),
    [view.numbers],
  );
  const wrong = useMemo(
    () => new Set(view.wrong.map(([row, col]) => `${row}:${col}`)),
    [view.wrong],
  );

  // On mount, take whichever copy has more in it. The server is authoritative
  // for everything that matters — checks used, status — so the only question
  // here is which grid has more of the player's typing in it.
  const [grid, setGrid] = useState<string[][]>(() => {
    const stored = readStored(challengeId);
    return stored && isRicher(stored.grid, view.letters) ? stored.grid : view.letters;
  });
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const [across, setAcross] = useState(true);

  // A ref so the unmount flush below sends the latest grid without re-running
  // (and re-flushing) on every keystroke.
  const latest = useRef(grid);
  latest.current = grid;

  // Server state wins whenever it moves — a check just came back, or the
  // session ended.
  useEffect(() => {
    if (over || view.checks > 0) setGrid(view.letters);
  }, [view.letters, view.checks, over]);

  const write = (next: string[][]) => {
    setGrid(next);
    try {
      localStorage.setItem(
        storageKey(challengeId),
        JSON.stringify({ grid: next, saved_at: Date.now() } satisfies Stored),
      );
    } catch {
      // Not worth interrupting play over. The flush below is the safety net,
      // and the server copy is what survives a device change either way.
    }
  };

  // Flush on leaving: tab hidden, or the component going away. Not on a timer —
  // a save every few seconds across 200 players is a load-test finding, and
  // every check carries the grid anyway.
  useEffect(() => {
    if (over) return;
    const flush = () => onSave(latest.current);
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      flush();
    };
  }, [challengeId, over]);

  const step = (row: number, col: number, backwards = false) => {
    const delta = backwards ? -1 : 1;
    let [nextRow, nextCol] = across ? [row, col + delta] : [row + delta, col];
    while (
      nextRow >= 0 &&
      nextCol >= 0 &&
      nextRow < view.height &&
      nextCol < view.width &&
      blocks.has(`${nextRow}:${nextCol}`)
    ) {
      [nextRow, nextCol] = across ? [nextRow, nextCol + delta] : [nextRow + delta, nextCol];
    }
    if (nextRow >= 0 && nextCol >= 0 && nextRow < view.height && nextCol < view.width) {
      setFocus([nextRow, nextCol]);
      document.getElementById(`cell-${nextRow}-${nextCol}`)?.focus();
    }
  };

  const type = (row: number, col: number, value: string) => {
    const next = Array.from({ length: view.height }, (_, r) =>
      Array.from({ length: view.width }, (_, c) => grid[r]?.[c] ?? ""),
    );
    next[row]![col] = value;
    write(next);
  };

  const currentClue = focus
    ? view.clues.find((clue) => {
        const [row, col] = focus;
        if (clue.direction !== (across ? "across" : "down")) return false;
        return across
          ? clue.row === row && col >= clue.col && col < clue.col + clue.length
          : clue.col === col && row >= clue.row && row < clue.row + clue.length;
      })
    : undefined;

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div
          className="mx-auto grid gap-0.5 sm:mx-0"
          style={{ gridTemplateColumns: `repeat(${view.width}, minmax(0, 2.5rem))` }}
          role="grid"
          aria-label="Crossword grid"
        >
          {Array.from({ length: view.height }).flatMap((_, row) =>
            Array.from({ length: view.width }).map((_, col) => {
              const key = `${row}:${col}`;
              if (blocks.has(key)) {
                return <div key={key} className="h-10 w-10 bg-ink/80" aria-hidden />;
              }
              const number = numbers.get(key);
              const isWrong = wrong.has(key);
              const focused = focus?.[0] === row && focus?.[1] === col;
              return (
                <div key={key} className="relative">
                  {number && (
                    <span className="pointer-events-none absolute left-0.5 top-0 text-[0.5rem] text-muted">
                      {number}
                    </span>
                  )}
                  <input
                    id={`cell-${row}-${col}`}
                    value={grid[row]?.[col] ?? ""}
                    disabled={over}
                    inputMode="text"
                    maxLength={1}
                    aria-label={`Row ${row + 1}, column ${col + 1}${
                      isWrong ? ", wrong" : ""
                    }`}
                    onFocus={() => setFocus([row, col])}
                    onClick={() => {
                      // A second click on the cell you are already in turns the
                      // entry, which is how every crossword works.
                      if (focused) setAcross((current) => !current);
                    }}
                    onChange={(event) => {
                      const letter = event.target.value.slice(-1).toUpperCase();
                      if (!/^[A-Z]?$/.test(letter)) return;
                      type(row, col, letter);
                      if (letter) step(row, col);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Backspace" && !grid[row]?.[col]) {
                        event.preventDefault();
                        step(row, col, true);
                      } else if (event.key === "ArrowRight") {
                        setAcross(true);
                        step(row, col);
                      } else if (event.key === "ArrowLeft") {
                        setAcross(true);
                        step(row, col, true);
                      } else if (event.key === "ArrowDown") {
                        setAcross(false);
                        step(row, col);
                      } else if (event.key === "ArrowUp") {
                        setAcross(false);
                        step(row, col, true);
                      }
                    }}
                    className={`h-10 w-10 border text-center text-lg font-semibold uppercase outline-none ${
                      // Marked wrong keeps a ring *and* a tint: the ring is the
                      // one that survives a colour-blind reading.
                      isWrong
                        ? "border-red-600 bg-red-100 ring-2 ring-red-500"
                        : focused
                          ? "border-ink bg-amber-50"
                          : "border-stone bg-white/70"
                    }`}
                  />
                </div>
              );
            }),
          )}
        </div>

        <div className="flex-1 text-sm">
          {(["across", "down"] as const).map((direction) => (
            <div key={direction} className="mb-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
                {direction}
              </h3>
              <ul className="mt-1 space-y-0.5">
                {view.clues
                  .filter((clue) => clue.direction === direction)
                  .map((clue) => (
                    <li
                      key={`${clue.number}-${clue.direction}`}
                      className={
                        currentClue?.number === clue.number &&
                        currentClue?.direction === clue.direction
                          ? "rounded bg-amber-100 px-1 font-medium"
                          : ""
                      }
                    >
                      <button
                        type="button"
                        className="text-left"
                        onClick={() => {
                          setAcross(direction === "across");
                          setFocus([clue.row, clue.col]);
                          document.getElementById(`cell-${clue.row}-${clue.col}`)?.focus();
                        }}
                      >
                        <strong>{clue.number}.</strong> {clue.clue}{" "}
                        <span className="text-muted">({clue.length})</span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted" role="status">
          {over
            ? state.status === "solved"
              ? "Solved."
              : "Out of checks."
            : `${view.checks_remaining} ${
                view.checks_remaining === 1 ? "check" : "checks"
              } left${view.wrong.length ? ` · ${view.wrong.length} wrong` : ""}`}
        </p>

        {!over && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onSave(grid)}
              className="rounded border border-stone px-3 py-1.5 text-sm"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => onPlay(grid)}
              disabled={pending}
              className="rounded bg-ink px-4 py-1.5 text-sm font-medium text-parchment disabled:opacity-50"
            >
              {pending ? "Checking…" : "Check"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
