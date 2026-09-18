import { Link } from "react-router-dom";

import type { CharacterSheet } from "../api/character";
import type { ChallengeListItem } from "../api/challenges";
import type { Me } from "../api/auth";

/**
 * First steps (spec 066 §3.1).
 *
 * **Derived, never stored.** Every one of these is answerable from data the
 * client already holds, and a `completed_steps` column would be a second source
 * of truth that could disagree with reality — a player who left a party would
 * still show the step ticked.
 *
 * The one thing that *is* stored is whether the whole list has ever been
 * finished, per browser. Once complete it is gone for good: a checklist that
 * comes back because somebody left a party reads as an accusation (§7.1).
 */
const DONE_KEY = "ctf.firstSteps.done";

export interface Step {
  id: string;
  label: string;
  done: boolean;
  /** Where it happens. "Go and solve something" is not guidance. */
  to: string;
  hint?: string;
  /** Shown but not yet reachable — the ladder is visible from the first hour. */
  locked?: boolean;
}

export function buildSteps(
  me: Me,
  sheet: CharacterSheet | undefined,
  challenges: ChallengeListItem[],
  firstZone: { name: string; slug: string } | null,
): Step[] {
  const solved = challenges.some((row) => row.solved);
  const classUnlocked = sheet?.class_unlocked ?? false;

  return [
    // One tick for free on arrival, which is how a checklist earns a first
    // glance rather than reading as a list of things you have not done.
    { id: "sign-in", label: "Sign in", done: true, to: "/" },
    { id: "party", label: "Join a party", done: me.team !== null, to: "/party" },
    {
      id: "solve",
      label: "Solve your first challenge",
      done: solved,
      to: "/challenges",
      hint: firstZone ? `start in ${firstZone.name}` : undefined,
    },
    {
      id: "skill",
      label: "Discover a skill",
      done: (sheet?.skills ?? []).some((skill) => skill.discovered),
      to: "/character",
      hint: "they appear as you earn XP in them",
    },
    {
      id: "class",
      label: "Choose a class",
      done: (sheet?.character_class ?? null) !== null,
      to: "/character",
      locked: !classUnlocked,
      hint: classUnlocked ? undefined : `level ${sheet?.class_unlock_level ?? 5}`,
    },
  ];
}

export function markDone(): void {
  try {
    localStorage.setItem(DONE_KEY, "1");
  } catch {
    // A convenience. Worst case it shows once more.
  }
}

export function alreadyDone(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === "1";
  } catch {
    return false;
  }
}

export default function FirstSteps({ steps }: { steps: Step[] }) {
  const done = steps.filter((step) => step.done).length;

  // Once finished, gone for good — remembered so it does not return if a step
  // is later undone.
  if (done === steps.length) {
    markDone();
    return null;
  }
  if (alreadyDone()) return null;

  return (
    <section className="rounded-lg border border-border-strong bg-surface-raised p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide">First steps</h2>
        <span className="text-xs text-content-muted tabular-nums">
          {done} of {steps.length}
        </span>
      </div>

      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {steps.map((step) => (
          <li key={step.id} className="flex items-baseline gap-2 text-sm">
            <span
              aria-hidden
              className={step.done ? "text-success" : "text-content-faint"}
            >
              {step.done ? "✓" : "○"}
            </span>
            <span className="min-w-0">
              {step.done || step.locked ? (
                <span className={step.locked ? "text-content-muted" : undefined}>
                  {step.label}
                </span>
              ) : (
                <Link to={step.to} className="hover:underline">
                  {step.label}
                </Link>
              )}
              {!step.done && step.hint && (
                <span className="ml-1 text-xs text-content-muted">({step.hint})</span>
              )}
              <span className="sr-only">{step.done ? " — done" : ""}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
