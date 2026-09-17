import { useQuery } from "@tanstack/react-query";

import {
  BOSS_TIER_CLASS,
  BOSS_TIER_LABEL,
  getStars,
  type Star,
} from "../api/bosses";

/**
 * Bosses this player has beaten (spec 031).
 *
 * Stars are derived from the solve rather than stored, so this needs no state
 * of its own — and a boss flagged after the fact simply appears here next time
 * the sheet loads.
 */
export default function StarsSection() {
  const stars = useQuery({ queryKey: ["stars"], queryFn: getStars });

  // Defensive: a partial response must not take the whole sheet down with it.
  const held = Array.isArray(stars.data) ? stars.data : [];
  if (stars.isPending || held.length === 0) return null;

  return (
    <section className="mt-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Bosses felled</h2>
        <span className="text-sm text-content-muted tabular-nums">
          {held.length} {held.length === 1 ? "star" : "stars"}
        </span>
      </div>

      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {held.map((star) => (
          <StarRow key={star.challenge_id} star={star} />
        ))}
      </ul>
    </section>
  );
}

function StarRow({ star }: { star: Star }) {
  return (
    <li className="flex items-center gap-3 rounded border border-border bg-surface-raised px-3 py-2">
      <span
        aria-hidden
        className={`text-2xl leading-none ${BOSS_TIER_CLASS[star.tier]}`}
      >
        ★
      </span>
      <span className="min-w-0">
        <p className="truncate text-sm font-semibold">{star.challenge_title}</p>
        {/* The tier name is always rendered, so the colour is never the only
            thing carrying the meaning. */}
        <p className="text-xs text-content-muted">
          {BOSS_TIER_LABEL[star.tier]} · {star.zone_name}
        </p>
      </span>
    </li>
  );
}
