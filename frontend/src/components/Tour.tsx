import { useEffect, useState } from "react";

/**
 * The furniture, explained once (spec 066 §3.2).
 *
 * Four stops, not ten. The tour explains what things *are*; `FirstSteps` keeps
 * pointing at the next useful thing all week. Neither replaces the other, which
 * is why the brief asked for both.
 *
 * **Remembered per browser**, not on the server. It is a convenience, and the
 * cost of a second showing on a second device is that somebody presses Skip —
 * a column and a migration to save one press is a bad trade.
 */
const SEEN_KEY = "ctf.tour.seen";
//: Listened for by this component, so the profile menu can reopen it without
//: either of them having to own the other's state.
export const REOPEN_EVENT = "ctf:tour:open";

const STOPS = [
  {
    title: "Your inbox",
    body: "Everything the dungeon tells you lands here — what you earned, and what happened. It is the record, so nothing is lost if you miss a pop-up.",
  },
  {
    title: "The board",
    body: "Every challenge, grouped by zone. Sealed zones show what opens them. Opening one keeps your place in the list.",
  },
  {
    title: "Your character",
    body: "Abilities, skills, achievements and loot. Skills appear as you earn XP in them, and a class is yours to choose once you reach the level for it.",
  },
  {
    title: "The System AI",
    body: "Bottom right. It will answer questions, occasionally usefully. It is also watching what you do, and has opinions.",
  },
];

export function markTourSeen(): void {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    // Worst case it shows once more.
  }
}

export function hasSeenTour(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    // Storage blocked: treat it as seen rather than showing a tour on every
    // single page load, which would be worse than never showing it.
    return true;
  }
}

/** Reopens the tour from anywhere — the profile menu uses this (§3.2). */
export function openTour(): void {
  window.dispatchEvent(new CustomEvent(REOPEN_EVENT));
}

export default function Tour() {
  const [step, setStep] = useState<number | null>(() => (hasSeenTour() ? null : 0));

  useEffect(() => {
    const onOpen = () => setStep(0);
    window.addEventListener(REOPEN_EVENT, onOpen);
    return () => window.removeEventListener(REOPEN_EVENT, onOpen);
  }, []);

  const close = () => {
    markTourSeen();
    setStep(null);
  };

  useEffect(() => {
    if (step === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  if (step === null) return null;

  const stop = STOPS[step]!;
  const last = step === STOPS.length - 1;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-content/40" onClick={close} aria-hidden />
      <div className="fixed inset-x-4 top-20 z-50 mx-auto max-w-sm rounded-lg border border-border-strong bg-surface-overlay p-4 shadow-xl">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Tour: ${stop.title}`}
        >
          <p className="text-xs text-content-muted tabular-nums">
            {step + 1} of {STOPS.length}
          </p>
          <h2 className="mt-1 text-lg font-semibold">{stop.title}</h2>
          <p className="mt-1 text-sm text-content-muted">{stop.body}</p>

          <div className="mt-4 flex items-center gap-3">
            {/* Skippable at every step, not only the first. */}
            <button type="button" onClick={close} className="text-sm underline">
              Skip
            </button>
            <button
              type="button"
              onClick={() => (last ? close() : setStep(step + 1))}
              className="ml-auto rounded bg-accent-strong px-3 py-1.5 text-sm font-medium text-accent-content"
            >
              {last ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
