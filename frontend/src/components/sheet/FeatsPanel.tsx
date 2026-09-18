import { useQuery } from "@tanstack/react-query";

import { getPublicAchievements, type PublicCharacter } from "../../api/character";
import BossStars from "../BossStars";
import { SheetPanel } from "./SheetPanel";

/**
 * What somebody else has actually done (spec 061 §5).
 *
 * Sits where the own sheet has Loot, because a stranger's inventory is not a
 * thing to browse — and the only part of it anybody else is meant to see, the
 * worn title, is already in the identity block.
 *
 * **Bosses felled live here and nowhere else on this page.** Spec 060 dropped
 * them from the *own* sheet on the reasoning that a player can look at their own
 * challenge list; you cannot look at somebody else's, so this is the only place
 * their kills appear.
 *
 * **Counts only, never XP** — including none implied. A per-zone points total
 * would be XP wearing a different hat.
 *
 * Deliberately absent: hints used and failed attempts. Both are real numbers we
 * hold, and neither belongs on a page colleagues open about each other.
 */
export default function FeatsPanel({ sheet }: { sheet: PublicCharacter }) {
  // The same query key the trophy case uses, so this shares its cached result
  // rather than prop-drilling the count through the page or fetching twice.
  const achievements = useQuery({
    queryKey: ["character", sheet.user_id, "achievements"],
    queryFn: () => getPublicAchievements(sheet.user_id),
  });

  return (
    <SheetPanel title="Feats" className="h-[19rem]">
      <dl className="mb-3 grid shrink-0 grid-cols-3 gap-2 text-center">
        <Counter label="Solved" value={sheet.solve_count} />
        <Counter label="Awards" value={achievements.data?.earned ?? 0} />
        <Counter label="Skills" value={`${sheet.skills.length}/${sheet.skills_total}`} />
      </dl>

      <div className="mb-3 flex shrink-0 items-center gap-2 border-y border-border py-2">
        <span className="text-xs uppercase tracking-wide text-content-muted">Bosses</span>
        <BossStars stars={sheet.stars} size="lg" />
      </div>

      <h3 className="mb-1 shrink-0 text-xs font-semibold uppercase tracking-wide text-content-muted">
        Where they hunt
      </h3>
      {/* Zones with no solves are omitted: a portrait, not an audit (§9.1). */}
      {sheet.zones.length === 0 ? (
        <p className="text-sm text-content-muted">Nothing solved yet.</p>
      ) : (
        <ul
          aria-label="Solves by zone"
          className="min-h-0 flex-1 divide-y divide-border overflow-y-auto"
        >
          {sheet.zones.map((zone) => (
            <li
              key={zone.zone_name}
              className="flex items-center justify-between gap-2 px-1 py-1 text-sm"
            >
              <span className="min-w-0 truncate">{zone.zone_name}</span>
              <span className="shrink-0 text-content-muted tabular-nums">{zone.solves}</span>
            </li>
          ))}
        </ul>
      )}
    </SheetPanel>
  );
}

function Counter({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded border border-border bg-surface py-1.5">
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      <dt className="text-[10px] uppercase tracking-wide text-content-muted">{label}</dt>
    </div>
  );
}
