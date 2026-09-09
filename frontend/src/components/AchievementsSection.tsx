import { useQuery } from "@tanstack/react-query";

import { getAchievements, type AchievementRow } from "../api/notifications";

/**
 * What this player has done, and what they have not (spec 028).
 *
 * Unearned rows are placeholders because the server sends no name for them —
 * the blur is honest rather than cosmetic, so there is nothing to read in
 * devtools. The total is public on purpose: it is something to aim at.
 */
export default function AchievementsSection() {
  const achievements = useQuery({
    queryKey: ["achievements"],
    queryFn: getAchievements,
  });

  if (achievements.isPending || !achievements.data) return null;
  // Defensive: a partial response must not take the whole sheet down with it.
  const { earned = 0, total = 0, items = [], rarest = [] } = achievements.data;
  if (total === 0) return null;

  return (
    <section className="mt-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Achievements</h2>
        <span className="text-sm text-muted tabular-nums">
          {earned} of {total} earned
        </span>
      </div>

      {rarest.length > 0 && (
        <>
          <h3 className="mt-3 text-sm font-semibold uppercase tracking-wide text-muted">
            Rarest held
          </h3>
          <ul className="mt-2 grid gap-2 sm:grid-cols-5">
            {rarest.map((row) => (
              <li
                key={row.id}
                className="rounded border border-torch/40 bg-torch/10 px-3 py-2"
              >
                <p className="text-sm font-semibold">{row.name}</p>
                <p className="mt-0.5 text-xs text-muted tabular-nums">
                  {formatRarity(row.rarity)} of players
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      <ul className="mt-4 space-y-1">
        {items.map((row) => (
          <Row key={row.id} row={row} />
        ))}
      </ul>
    </section>
  );
}

/** Below a tenth of a percent still reads as "<0.1%" rather than rounding to
 *  zero, which would look like nobody has it including the holder. */
function formatRarity(rarity: number | null): string {
  if (rarity === null) return "—";
  const percent = rarity * 100;
  if (percent > 0 && percent < 0.1) return "<0.1%";
  return `${percent.toFixed(percent < 10 ? 1 : 0)}%`;
}

function Row({ row }: { row: AchievementRow }) {
  if (!row.earned) {
    return (
      <li className="flex items-center justify-between rounded border border-stone bg-white/30 px-3 py-2">
        <span className="select-none text-sm blur-[3px]" aria-hidden>
          Undiscovered achievement
        </span>
        <span className="sr-only">Undiscovered achievement</span>
        <span className="text-sm text-muted">—</span>
      </li>
    );
  }

  return (
    <li className="rounded border border-stone bg-white/50 px-3 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-semibold">{row.name}</p>
        <span className="text-xs text-muted tabular-nums">
          {formatRarity(row.rarity)}
        </span>
      </div>
      <p className="mt-0.5 text-sm text-muted">{row.description}</p>
    </li>
  );
}
