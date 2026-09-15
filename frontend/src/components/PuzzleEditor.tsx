import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import {
  clearPuzzle,
  setPuzzle,
  type AdminChallengeDetail,
  type ConnectionsConfig,
  type CrosswordConfig,
  type WordleConfig,
} from "../api/adminChallenges";
import { KIND_LABEL, type PuzzleKind } from "../api/puzzles";
import { ApiError } from "../api/client";
import ErrorMessage from "./ErrorMessage";

/**
 * Authoring a daily puzzle (spec 044 §7).
 *
 * The server's engine is the authority on whether a puzzle is valid; everything
 * here is convenience. So this deliberately does not pre-validate — it sends what
 * was typed and shows what came back, field marker included, which is one rule
 * to keep in step instead of two.
 */

const KINDS: PuzzleKind[] = ["wordle", "connections", "crossword"];

const EMPTY_CONNECTIONS: ConnectionsConfig = {
  groups: [1, 2, 3, 4].map((level) => ({ name: "", level, members: ["", "", "", ""] })),
  max_mistakes: 4,
};

function emptyCrossword(width = 5, height = 5): CrosswordConfig {
  return { width, height, blocks: [], entries: [], max_checks: 3 };
}

export default function PuzzleEditor({
  challenge,
  onChanged,
}: {
  challenge: AdminChallengeDetail;
  onChanged: () => void;
}) {
  const existing = challenge.puzzle;
  const [kind, setKind] = useState<PuzzleKind | "">(existing?.kind ?? "");
  const [config, setConfig] = useState<Record<string, unknown>>(existing?.config ?? {});
  const [notes, setNotes] = useState<string[]>([]);

  const save = useMutation({
    mutationFn: () => setPuzzle(challenge.id, kind as PuzzleKind, config),
    onSuccess: (result) => {
      setConfig(result.config);
      setNotes(result.notes);
      onChanged();
    },
  });

  const clear = useMutation({
    mutationFn: () => clearPuzzle(challenge.id),
    onSuccess: () => {
      setKind("");
      setConfig({});
      setNotes([]);
      onChanged();
    },
  });

  const chooseKind = (next: PuzzleKind | "") => {
    setKind(next);
    setNotes([]);
    if (next === existing?.kind) setConfig(existing.config);
    else if (next === "connections") setConfig(EMPTY_CONNECTIONS as never);
    else if (next === "crossword") setConfig(emptyCrossword() as never);
    else if (next === "wordle") setConfig({ answer: "", max_guesses: 6, extra_words: [] });
    else setConfig({});
  };

  // The engine names the field it objects to, so the message can sit against it
  // rather than at the top of a form with twenty inputs.
  const badField =
    save.error instanceof ApiError ? (save.error.details.field as string | undefined) : undefined;

  if (challenge.answers.length > 0 && !existing) {
    return (
      <p className="text-sm text-muted">
        This challenge has {challenge.answers.length}{" "}
        {challenge.answers.length === 1 ? "flag" : "flags"}. A puzzle is played rather than
        answered — remove the flags first.
      </p>
    );
  }

  return (
    <div>
      <label className="block text-sm font-medium" htmlFor="puzzle-kind">
        Game
      </label>
      <select
        id="puzzle-kind"
        value={kind}
        onChange={(event) => chooseKind(event.target.value as PuzzleKind | "")}
        className="mt-1 rounded border border-stone px-3 py-2"
      >
        <option value="">None — an ordinary challenge</option>
        {KINDS.map((option) => (
          <option key={option} value={option}>
            {KINDS_LABEL(option)}
          </option>
        ))}
      </select>

      {existing && (
        <p className="mt-2 text-sm text-muted">
          {existing.sessions} played · {existing.solved} solved · {existing.failed} lost
          {existing.sessions > 4 && existing.solved === 0 && (
            <strong className="ml-1 text-torch">
              Nobody has finished this one.
            </strong>
          )}
        </p>
      )}

      {kind === "wordle" && (
        <WordleFields config={config as unknown as WordleConfig} onChange={setConfig} />
      )}
      {kind === "connections" && (
        <ConnectionsFields config={config as unknown as ConnectionsConfig} onChange={setConfig} />
      )}
      {kind === "crossword" && (
        <CrosswordFields config={config as unknown as CrosswordConfig} onChange={setConfig} />
      )}

      {badField && (
        <p className="mt-3 text-sm text-torch">
          Problem in <code>{badField}</code>.
        </p>
      )}
      <ErrorMessage error={save.error} />
      <ErrorMessage error={clear.error} />

      {notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-muted">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex gap-2">
        {kind && (
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="rounded bg-ink px-4 py-2 text-sm font-medium text-parchment disabled:opacity-50"
          >
            {save.isPending ? "Checking…" : "Save puzzle"}
          </button>
        )}
        {existing && (
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  `Remove the ${KIND_LABEL[existing.kind]} from "${challenge.title}"? ` +
                    `${existing.sessions} player session(s) go with it.`,
                )
              ) {
                clear.mutate();
              }
            }}
            className="rounded border border-torch px-4 py-2 text-sm text-torch"
          >
            Remove puzzle
          </button>
        )}
      </div>
    </div>
  );
}

function KINDS_LABEL(kind: PuzzleKind) {
  return KIND_LABEL[kind];
}

function WordleFields({
  config,
  onChange,
}: {
  config: WordleConfig;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const set = (patch: Partial<WordleConfig>) =>
    onChange({ ...config, ...patch } as unknown as Record<string, unknown>);

  return (
    <div className="mt-4 space-y-3">
      <div>
        <label className="block text-sm font-medium" htmlFor="wordle-answer">
          Answer (five letters)
        </label>
        <input
          id="wordle-answer"
          value={config.answer ?? ""}
          onChange={(event) => set({ answer: event.target.value.toUpperCase() })}
          maxLength={5}
          className="mt-1 w-40 rounded border border-stone px-3 py-2 font-mono uppercase"
        />
      </div>
      <div>
        <label className="block text-sm font-medium" htmlFor="wordle-guesses">
          Guesses
        </label>
        <input
          id="wordle-guesses"
          type="number"
          min={1}
          max={12}
          value={config.max_guesses ?? 6}
          onChange={(event) => set({ max_guesses: Number(event.target.value) })}
          className="mt-1 w-24 rounded border border-stone px-3 py-2"
        />
      </div>
      <div>
        <label className="block text-sm font-medium" htmlFor="wordle-extra">
          Extra accepted guesses
        </label>
        <p className="text-xs text-muted">
          Security terms the shipped word list has never heard of. Comma separated; five letters
          each. The answer itself is always accepted.
        </p>
        <input
          id="wordle-extra"
          value={(config.extra_words ?? []).join(", ")}
          onChange={(event) =>
            set({
              extra_words: event.target.value
                .split(",")
                .map((word) => word.trim().toUpperCase())
                .filter(Boolean),
            })
          }
          className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={config.reveal_on_fail ?? true}
          onChange={(event) => set({ reveal_on_fail: event.target.checked })}
        />
        Show the answer to a player who runs out
      </label>
    </div>
  );
}

function ConnectionsFields({
  config,
  onChange,
}: {
  config: ConnectionsConfig;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const groups = config.groups ?? EMPTY_CONNECTIONS.groups;

  const update = (index: number, patch: Partial<(typeof groups)[number]>) => {
    const next = groups.map((group, position) =>
      position === index ? { ...group, ...patch } : group,
    );
    onChange({ ...config, groups: next } as unknown as Record<string, unknown>);
  };

  return (
    <div className="mt-4 space-y-4">
      <p className="text-xs text-muted">
        Four groups of four. Level 1 is the gentlest and 4 the trap — that is the order they are
        revealed in. All sixteen tiles must be different.
      </p>
      {groups.map((group, index) => (
        <div key={group.level} className="rounded border border-stone p-3">
          <label className="block text-sm font-medium" htmlFor={`group-${index}`}>
            Level {group.level} — what connects them
          </label>
          <input
            id={`group-${index}`}
            value={group.name}
            onChange={(event) => update(index, { name: event.target.value })}
            className="mt-1 w-full rounded border border-stone px-3 py-1.5"
          />
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[0, 1, 2, 3].map((slot) => (
              <input
                key={slot}
                value={group.members?.[slot] ?? ""}
                aria-label={`Level ${group.level}, tile ${slot + 1}`}
                onChange={(event) => {
                  const members = [0, 1, 2, 3].map((position) =>
                    position === slot ? event.target.value : (group.members?.[position] ?? ""),
                  );
                  update(index, { members });
                }}
                className="rounded border border-stone px-2 py-1.5 text-sm"
              />
            ))}
          </div>
        </div>
      ))}
      <div>
        <label className="block text-sm font-medium" htmlFor="max-mistakes">
          Mistakes allowed
        </label>
        <input
          id="max-mistakes"
          type="number"
          min={1}
          max={8}
          value={config.max_mistakes ?? 4}
          onChange={(event) =>
            onChange({
              ...config,
              max_mistakes: Number(event.target.value),
            } as unknown as Record<string, unknown>)
          }
          className="mt-1 w-24 rounded border border-stone px-3 py-2"
        />
      </div>
    </div>
  );
}

function CrosswordFields({
  config,
  onChange,
}: {
  config: CrosswordConfig;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const width = config.width ?? 5;
  const height = config.height ?? 5;
  const blocks = config.blocks ?? [];
  const entries = config.entries ?? [];

  const set = (patch: Partial<CrosswordConfig>) =>
    onChange({ ...config, ...patch } as unknown as Record<string, unknown>);

  const isBlock = (row: number, col: number) =>
    blocks.some(([r, c]) => r === row && c === col);

  const toggleBlock = (row: number, col: number) => {
    set({
      blocks: isBlock(row, col)
        ? blocks.filter(([r, c]) => !(r === row && c === col))
        : [...blocks, [row, col]],
    });
  };

  // Numbering is derived by the server and comes back on save, so an entry the
  // author has just added shows "—" until then rather than a guessed number that
  // might disagree with the grid.
  return (
    <div className="mt-4 space-y-4">
      <div className="flex gap-3">
        {(["width", "height"] as const).map((dimension) => (
          <div key={dimension}>
            <label className="block text-sm font-medium" htmlFor={`cw-${dimension}`}>
              {dimension === "width" ? "Width" : "Height"}
            </label>
            <input
              id={`cw-${dimension}`}
              type="number"
              min={3}
              max={7}
              value={config[dimension] ?? 5}
              onChange={(event) => set({ [dimension]: Number(event.target.value) })}
              className="mt-1 w-20 rounded border border-stone px-3 py-2"
            />
          </div>
        ))}
        <div>
          <label className="block text-sm font-medium" htmlFor="cw-checks">
            Checks
          </label>
          <input
            id="cw-checks"
            type="number"
            min={1}
            max={10}
            value={config.max_checks ?? 3}
            onChange={(event) => set({ max_checks: Number(event.target.value) })}
            className="mt-1 w-20 rounded border border-stone px-3 py-2"
          />
        </div>
      </div>

      <div>
        <p className="text-sm font-medium">Grid</p>
        <p className="text-xs text-muted">Click a cell to make it a block.</p>
        <div
          className="mt-2 grid gap-0.5"
          style={{ gridTemplateColumns: `repeat(${width}, 2rem)` }}
        >
          {Array.from({ length: height }).flatMap((_, row) =>
            Array.from({ length: width }).map((_, col) => (
              <button
                key={`${row}:${col}`}
                type="button"
                aria-label={`Row ${row + 1}, column ${col + 1}${
                  isBlock(row, col) ? ", block" : ""
                }`}
                aria-pressed={isBlock(row, col)}
                onClick={() => toggleBlock(row, col)}
                className={`h-8 w-8 border border-stone ${
                  isBlock(row, col) ? "bg-ink" : "bg-white"
                }`}
              />
            )),
          )}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Entries</p>
          <button
            type="button"
            onClick={() =>
              set({
                entries: [
                  ...entries,
                  {
                    number: 0,
                    direction: "across",
                    row: 0,
                    col: 0,
                    length: 0,
                    answer: "",
                    clue: "",
                  },
                ],
              })
            }
            className="rounded border border-stone px-2 py-1 text-sm"
          >
            Add entry
          </button>
        </div>

        <ul className="mt-2 space-y-2">
          {entries.map((entry, index) => (
            <li key={index} className="rounded border border-stone p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-8 text-sm text-muted">{entry.number || "—"}</span>
                <select
                  value={entry.direction}
                  aria-label={`Entry ${index + 1} direction`}
                  onChange={(event) =>
                    set({
                      entries: entries.map((candidate, position) =>
                        position === index
                          ? {
                              ...candidate,
                              direction: event.target.value as "across" | "down",
                            }
                          : candidate,
                      ),
                    })
                  }
                  className="rounded border border-stone px-2 py-1 text-sm"
                >
                  <option value="across">across</option>
                  <option value="down">down</option>
                </select>
                {(["row", "col"] as const).map((axis) => (
                  <input
                    key={axis}
                    type="number"
                    min={0}
                    value={entry[axis]}
                    aria-label={`Entry ${index + 1} ${axis}`}
                    onChange={(event) =>
                      set({
                        entries: entries.map((candidate, position) =>
                          position === index
                            ? { ...candidate, [axis]: Number(event.target.value) }
                            : candidate,
                        ),
                      })
                    }
                    className="w-16 rounded border border-stone px-2 py-1 text-sm"
                  />
                ))}
                <input
                  value={entry.answer}
                  aria-label={`Entry ${index + 1} answer`}
                  placeholder="ANSWER"
                  onChange={(event) =>
                    set({
                      entries: entries.map((candidate, position) =>
                        position === index
                          ? { ...candidate, answer: event.target.value.toUpperCase() }
                          : candidate,
                      ),
                    })
                  }
                  className="w-28 rounded border border-stone px-2 py-1 font-mono text-sm uppercase"
                />
                <button
                  type="button"
                  aria-label={`Remove entry ${index + 1}`}
                  onClick={() =>
                    set({ entries: entries.filter((_, position) => position !== index) })
                  }
                  className="text-sm text-torch"
                >
                  Remove
                </button>
              </div>
              <input
                value={entry.clue}
                aria-label={`Entry ${index + 1} clue`}
                placeholder="Clue"
                onChange={(event) =>
                  set({
                    entries: entries.map((candidate, position) =>
                      position === index ? { ...candidate, clue: event.target.value } : candidate,
                    ),
                  })
                }
                className="mt-2 w-full rounded border border-stone px-2 py-1 text-sm"
              />
            </li>
          ))}
        </ul>
        {entries.length === 0 && (
          <p className="mt-2 text-sm text-muted">No entries yet.</p>
        )}
      </div>
    </div>
  );
}
