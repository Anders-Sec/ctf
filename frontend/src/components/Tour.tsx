import { useEffect, useLayoutEffect, useState } from "react";

/**
 * The furniture, explained once (spec 066 §3.2).
 *
 * §3.2 asked for *"numbered callouts on the nav"*, and the first build was a
 * centred dialog that described the nav without pointing at it — which is a
 * different and much weaker thing. This one **spotlights the real element**:
 * it finds the target by its `data-tour` attribute, cuts a hole in the overlay
 * around it, and puts the callout beside it.
 *
 * Four stops, not ten. The tour explains what things *are*; `FirstSteps` keeps
 * pointing at the next useful thing all week.
 *
 * **Remembered per browser**, not on the server: a column and a migration to
 * save one press of Skip is a bad trade.
 */
const SEEN_KEY = "ctf.tour.seen";
//: Listened for by this component, so the profile menu and the settings page can
//: reopen it without either of them having to own its state.
export const REOPEN_EVENT = "ctf:tour:open";

interface Stop {
  /** Matches `data-tour` on the real element. */
  target: string;
  title: string;
  body: string;
}

const STOPS: Stop[] = [
  {
    target: "inbox",
    title: "Your inbox",
    body: "Everything the dungeon tells you lands here — what you earned, and what happened. It is the record, so nothing is lost if you miss a pop-up.",
  },
  {
    target: "board",
    title: "The board",
    body: "Every challenge, grouped by zone. Sealed zones show what opens them, and opening a challenge keeps your place in the list.",
  },
  {
    target: "character",
    title: "Your character",
    body: "Abilities, skills, achievements and loot. Skills appear as you earn XP in them, and a class is yours to choose once you reach the level for it.",
  },
  {
    target: "assistant",
    title: "The System AI",
    body: "It will answer questions, occasionally usefully. It is also watching what you do, and has opinions.",
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

/** Reopens the tour from anywhere — the profile menu and settings use this. */
export function openTour(): void {
  window.dispatchEvent(new CustomEvent(REOPEN_EVENT));
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export default function Tour() {
  const [step, setStep] = useState<number | null>(() => (hasSeenTour() ? null : 0));
  const [box, setBox] = useState<Box | null>(null);

  useEffect(() => {
    const onOpen = () => setStep(0);
    window.addEventListener(REOPEN_EVENT, onOpen);
    return () => window.removeEventListener(REOPEN_EVENT, onOpen);
  }, []);

  const close = () => {
    markTourSeen();
    setStep(null);
  };

  // Measured after paint, so the element is where it is going to be. Re-measured
  // on resize and scroll because a highlight that drifts off its target is worse
  // than none — it points confidently at the wrong thing.
  useLayoutEffect(() => {
    if (step === null) {
      setBox(null);
      return;
    }
    const measure = () => {
      const stop = STOPS[step];
      const element = stop
        ? document.querySelector<HTMLElement>(`[data-tour="${stop.target}"]`)
        : null;
      if (!element) {
        setBox(null);
        return;
      }
      const rect = element.getBoundingClientRect();
      setBox({ top: rect.top, left: rect.left, width: rect.width, height: rect.height });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);

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
  const padding = 6;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-content/50" onClick={close} aria-hidden />

      {/* The hole. A ring plus a shadow the size of the viewport, so the target
          sits lit while everything else stays under the dim. */}
      {box && (
        <div
          aria-hidden
          className="pointer-events-none fixed z-40 rounded ring-2 ring-accent"
          style={{
            top: box.top - padding,
            left: box.left - padding,
            width: box.width + padding * 2,
            height: box.height + padding * 2,
            boxShadow: "0 0 0 9999px rgb(var(--content) / 0.5)",
          }}
        />
      )}

      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Tour: ${stop.title}`}
        // Beside the target when there is one, centred when there is not — a
        // page without the nav should still be able to show the tour rather
        // than pointing at nothing.
        className="fixed z-50 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border-strong bg-surface-overlay p-4 shadow-xl"
        style={
          box
            ? { top: Math.min(box.top + box.height + 12, window.innerHeight - 200), left: Math.max(16, Math.min(box.left, window.innerWidth - 304)) }
            : { top: 96, left: "50%", transform: "translateX(-50%)" }
        }
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
          {step > 0 && (
            <button
              type="button"
              onClick={() => setStep(step - 1)}
              className="text-sm underline"
            >
              Back
            </button>
          )}
          <button
            type="button"
            onClick={() => (last ? close() : setStep(step + 1))}
            className="ml-auto rounded bg-accent-strong px-3 py-1.5 text-sm font-medium text-accent-content"
          >
            {last ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}
