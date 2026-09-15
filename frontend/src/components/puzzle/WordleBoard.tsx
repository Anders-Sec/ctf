import { useEffect, useState } from "react";

import type { LetterVerdict, PuzzleState, WordleView } from "../../api/puzzles";

/**
 * Wordle (spec 044 §4.1).
 *
 * Every verdict on this board was computed by the server. Nothing here knows the
 * answer, and there is deliberately no client-side scoring to keep in step with
 * the engine's duplicate-letter rule.
 */

const KEYS = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

/** Colour *and* a mark, never colour alone.
 *
 *  Around 1 in 12 men has some form of colour blindness, and green/yellow is the
 *  pairing that goes. The mark is what the tile means, spelled out; the colour is
 *  the fast path for everyone who can use it. */
const VERDICT_STYLE: Record<LetterVerdict, { className: string; mark: string; label: string }> = {
  exact: {
    className: "border-transparent bg-emerald-600 text-white",
    mark: "●",
    label: "right letter, right place",
  },
  present: {
    className: "border-transparent bg-amber-500 text-white",
    mark: "▲",
    label: "right letter, wrong place",
  },
  absent: {
    className: "border-transparent bg-stone-500 text-white",
    mark: "×",
    label: "not in the word",
  },
};

/** The best verdict a letter has earned so far, for the keyboard hint. */
function keyboardState(view: WordleView): Record<string, LetterVerdict> {
  const rank: Record<LetterVerdict, number> = { absent: 0, present: 1, exact: 2 };
  const best: Record<string, LetterVerdict> = {};
  for (const row of view.guesses) {
    row.guess.split("").forEach((letter, index) => {
      const verdict = row.verdicts[index];
      if (!verdict) return;
      const current = best[letter];
      if (!current || rank[verdict] > rank[current]) best[letter] = verdict;
    });
  }
  return best;
}

export default function WordleBoard({
  state,
  onPlay,
  pending,
  error,
}: {
  state: PuzzleState;
  onPlay: (guess: string) => void;
  pending: boolean;
  error: string | null;
}) {
  const view = state.puzzle as WordleView;
  const [draft, setDraft] = useState("");
  const over = state.status === "solved" || state.status === "failed";

  // Cleared when a guess lands, so the next one starts empty — but not when the
  // guess was refused, where the player wants to edit what they typed.
  useEffect(() => {
    if (!pending && !error) setDraft("");
  }, [view.guesses.length, pending, error]);

  const submit = () => {
    if (draft.length === view.length && !pending && !over) onPlay(draft);
  };

  const type = (letter: string) => {
    if (!over && draft.length < view.length) setDraft(draft + letter);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Never steal typing from a real input — the hint panel and the assistant
      // both live on this page.
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;

      if (event.key === "Enter") submit();
      else if (event.key === "Backspace") setDraft((current) => current.slice(0, -1));
      else if (/^[a-zA-Z]$/.test(event.key)) type(event.key.toUpperCase());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const keys = keyboardState(view);
  const rows = [
    ...view.guesses,
    ...(over ? [] : [{ guess: draft.padEnd(view.length), verdicts: null }]),
  ];
  const blanks = Math.max(0, view.max_guesses - rows.length);

  return (
    <div>
      <div
        className="flex flex-col items-center gap-1.5"
        role="group"
        aria-label={`Wordle, ${view.guesses_remaining} of ${view.max_guesses} guesses left`}
      >
        {rows.map((row, rowIndex) => (
          <div key={rowIndex} className="flex gap-1.5">
            {Array.from({ length: view.length }).map((_, index) => {
              const letter = row.guess[index]?.trim() ?? "";
              const verdict = row.verdicts?.[index];
              const style = verdict ? VERDICT_STYLE[verdict] : null;
              return (
                <div
                  key={index}
                  // "Guess 2, letter 3: D, not in the word" — the whole game in
                  // one string. Named by position so a tile is never confused
                  // with the keyboard key for the same letter, which carries its
                  // own hint and would otherwise read identically.
                  aria-label={
                    row.verdicts
                      ? `Guess ${rowIndex + 1}, letter ${index + 1}: ${letter}${
                          verdict ? `, ${VERDICT_STYLE[verdict].label}` : ""
                        }`
                      : `Your guess, letter ${index + 1}: ${letter || "empty"}`
                  }
                  className={`flex h-12 w-12 items-center justify-center rounded border-2 text-xl font-semibold uppercase ${
                    style ? style.className : "border-stone bg-white/60"
                  }`}
                >
                  <span aria-hidden>{letter}</span>
                  {style && (
                    <span className="ml-0.5 text-[0.6rem] opacity-80" aria-hidden>
                      {style.mark}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}

        {Array.from({ length: blanks }).map((_, rowIndex) => (
          <div key={`blank-${rowIndex}`} className="flex gap-1.5">
            {Array.from({ length: view.length }).map((_, index) => (
              <div
                key={index}
                className="h-12 w-12 rounded border-2 border-stone/50"
                aria-hidden
              />
            ))}
          </div>
        ))}
      </div>

      <p className="mt-3 text-center text-sm text-muted" role="status">
        {over
          ? state.status === "solved"
            ? "Solved."
            : view.answer
              ? `Out of guesses. It was ${view.answer}.`
              : "Out of guesses."
          : `${view.guesses_remaining} ${view.guesses_remaining === 1 ? "guess" : "guesses"} left`}
      </p>

      {!over && (
        <div className="mt-4 flex flex-col items-center gap-1.5">
          {KEYS.map((row, rowIndex) => (
            <div key={row} className="flex gap-1">
              {rowIndex === 2 && (
                <KeyButton wide onClick={submit} disabled={draft.length !== view.length || pending}>
                  Enter
                </KeyButton>
              )}
              {row.split("").map((letter) => (
                <KeyButton
                  key={letter}
                  onClick={() => type(letter)}
                  verdict={keys[letter]}
                  disabled={pending}
                >
                  {letter}
                </KeyButton>
              ))}
              {rowIndex === 2 && (
                <KeyButton wide onClick={() => setDraft(draft.slice(0, -1))}>
                  ⌫
                </KeyButton>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KeyButton({
  children,
  onClick,
  verdict,
  wide,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  verdict?: LetterVerdict;
  wide?: boolean;
  disabled?: boolean;
}) {
  const style = verdict ? VERDICT_STYLE[verdict] : null;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={
        typeof children === "string" && style ? `${children}, ${style.label}` : undefined
      }
      className={`h-11 rounded text-sm font-semibold disabled:opacity-50 ${
        wide ? "px-3" : "w-8 sm:w-9"
      } ${style ? style.className : "border border-stone bg-white/70"}`}
    >
      {children}
    </button>
  );
}
