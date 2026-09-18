import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getClasses, setMyClass, type CharacterSheet } from "../../api/character";
import Avatar from "../Avatar";
import ErrorMessage from "../ErrorMessage";
import { RARITY_TEXT } from "../classRarity";
import { Fact } from "./SheetPanel";

/**
 * The identity block (spec 060 §3).
 *
 * Full width across the top, because that is where a 5e sheet puts identity and
 * for the same reason: it is the one part of the page that answers "who is
 * this". It also collapses three blocks the old sheet had apart — the header,
 * a Class section, and a Level/XP section that repeated the level already in the
 * header.
 *
 * **This is the one screen allowed to show XP** (spec 059 §2), so it shows the
 * numbers rather than only a bar.
 */
export default function PlayerInfo({ sheet }: { sheet: CharacterSheet }) {
  const [choosing, setChoosing] = useState(false);

  return (
    <section className="rounded-lg border border-border-strong bg-surface-raised p-4">
      <div className="flex flex-wrap items-start gap-4">
        <Avatar
          userId={sheet.user_id}
          displayName={sheet.display_name}
          hasAvatar={sheet.has_avatar}
          size={56}
        />

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold tracking-tight">
            {sheet.display_name}
          </h1>
          {sheet.equipped_title && (
            // The name plate everybody else sees on the board. Its owner could
            // only find it inside the loot inventory before spec 060.
            <p className="truncate text-sm italic text-content-muted">
              {sheet.equipped_title}
            </p>
          )}
        </div>

        <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Fact label="Class">
            <button
              type="button"
              onClick={() => setChoosing(true)}
              className={`font-medium underline decoration-dotted underline-offset-2 ${
                sheet.character_class
                  ? (RARITY_TEXT[sheet.character_class.rarity] ?? "")
                  : "text-content-muted"
              }`}
            >
              {sheet.character_class?.name ?? "Classless"}
            </button>
          </Fact>
          <Fact label="Level">
            <span className="font-medium tabular-nums">{sheet.level}</span>
          </Fact>
          <Fact label="Rank">
            <span className="font-medium tabular-nums">
              {sheet.rank === null ? "unranked" : `#${sheet.rank}`}
            </span>
          </Fact>
          <Fact label="Party">
            {sheet.party ? (
              <Link to="/party" className="font-medium hover:underline">
                {sheet.party.name}
              </Link>
            ) : (
              <span className="text-content-muted">none</span>
            )}
          </Fact>
        </dl>
      </div>

      <div className="mt-3">
        <div
          className="h-2.5 overflow-hidden rounded-full bg-surface-sunken"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={sheet.xp_into_level + sheet.xp_to_next}
          aria-valuenow={sheet.xp_into_level}
          aria-label={`${sheet.xp_into_level} XP into level ${sheet.level}`}
        >
          <div
            className="h-full bg-accent-strong"
            style={{ width: `${progress(sheet.xp_into_level, sheet.xp_to_next)}%` }}
          />
        </div>
        <p className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-content-muted">
          <span className="tabular-nums">
            {sheet.xp_to_next > 0
              ? `${sheet.xp_into_level.toLocaleString()} / ${(sheet.xp_into_level + sheet.xp_to_next).toLocaleString()} XP to level ${sheet.level + 1}`
              : "Top of the curve for now"}
          </span>
          {/* The number a player quotes at somebody (§9.1). */}
          <span className="tabular-nums">{sheet.total_xp.toLocaleString()} XP total</span>
        </p>
      </div>

      {choosing && <ClassDialog sheet={sheet} onClose={() => setChoosing(false)} />}
    </section>
  );
}

function progress(into: number, toNext: number): number {
  const span = into + toNext;
  if (span <= 0) return 100;
  return Math.min(100, Math.round((into / span) * 100));
}

/**
 * Choosing a class (spec 060 §4).
 *
 * A dialog rather than a panel because the sheet has to fit a screen and this is
 * something a player does rarely; a dialog rather than a route because the
 * roster is four fields and a sentence.
 */
function ClassDialog({ sheet, onClose }: { sheet: CharacterSheet; onClose: () => void }) {
  const queryClient = useQueryClient();

  const roster = useQuery({
    queryKey: ["character", "classes"],
    queryFn: getClasses,
    enabled: sheet.class_unlocked,
  });
  const choose = useMutation({
    mutationFn: (classId: string | null) => setMyClass(classId),
    onSuccess: (updated) => {
      queryClient.setQueryData(["character", "me"], updated);
      onClose();
    },
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-content/30" onClick={onClose} aria-hidden />
      <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
        <div
          role="dialog"
          aria-label="Choose a class"
          className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-lg border border-border-strong bg-surface-overlay p-5 shadow-xl"
        >
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg font-semibold">Your calling</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close class chooser"
              className="text-xl leading-none"
            >
              ×
            </button>
          </div>

          {!sheet.class_unlocked ? (
            <p className="mt-4 text-sm text-content-muted">
              Reach level {sheet.class_unlock_level} to choose a class.
            </p>
          ) : (
            <ul className="mt-4 flex flex-col gap-1">
              {/* Unlocked classes only — the server never sends the rest, so the
                  roster stays a mystery until a class is earned (spec 024). */}
              <ClassChoice
                name="Classless"
                description="No calling yet."
                selected={sheet.character_class === null}
                disabled={choose.isPending}
                onChoose={() => choose.mutate(null)}
              />
              {(roster.data ?? []).map((option) => (
                <ClassChoice
                  key={option.id}
                  name={option.name}
                  description={option.description}
                  rarity={option.rarity}
                  selected={option.id === sheet.character_class?.id}
                  disabled={choose.isPending}
                  onChoose={() => choose.mutate(option.id)}
                />
              ))}
            </ul>
          )}

          {/* The System AI (spec 013) commenting on what it has watched the
              player do. A server-side template, not a model call — its voice,
              not its reasoning. */}
          {sheet.suggested_class_line && (
            <p className="mt-4 border-l-2 border-accent pl-3 text-sm italic text-content-muted">
              {sheet.suggested_class_line}
            </p>
          )}

          <ErrorMessage error={choose.error} />
        </div>
      </div>
    </>
  );
}

function ClassChoice({
  name,
  description,
  rarity,
  selected,
  disabled,
  onChoose,
}: {
  name: string;
  description: string | null;
  rarity?: string;
  selected: boolean;
  disabled: boolean;
  onChoose: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onChoose}
        disabled={disabled}
        aria-pressed={selected}
        className={`w-full rounded border px-3 py-2 text-left disabled:opacity-50 ${
          selected ? "border-accent-strong bg-accent/10" : "border-border"
        }`}
      >
        <span className="flex items-baseline justify-between gap-2">
          <span className={`font-medium ${rarity ? (RARITY_TEXT[rarity] ?? "") : ""}`}>
            {name}
          </span>
          {rarity && (
            // The rarity's name, not only its colour.
            <span className="text-xs text-content-muted">{rarity}</span>
          )}
        </span>
        {description && (
          <span className="mt-0.5 block text-xs text-content-muted">{description}</span>
        )}
      </button>
    </li>
  );
}
