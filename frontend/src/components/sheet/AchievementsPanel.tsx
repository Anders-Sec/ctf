import { useQuery } from "@tanstack/react-query";

import { getAchievements, type AchievementRow } from "../../api/notifications";
import { FilteredList, SheetPanel } from "./SheetPanel";

/**
 * What this player has done, and what they have not (specs 028, 060 §3).
 *
 * Unearned rows are placeholders because the server sends **no name** for them —
 * the blur is honest rather than cosmetic, so there is nothing to read in
 * devtools. That is also why search only ever matches earned rows, and why the
 * panel says so rather than leaving a player to wonder why a name they half
 * remember will not come up.
 *
 * The total is public on purpose: it is something to aim at.
 */

/** Below a tenth of a percent reads as "<0.1%" rather than rounding to zero,
 *  which would look like nobody has it including the holder. */
export function formatRarity(rarity: number | null): string {
  if (rarity === null) return "—";
  const percent = rarity * 100;
  if (percent > 0 && percent < 0.1) return "<0.1%";
  return `${percent.toFixed(percent < 10 ? 1 : 0)}%`;
}

export default function AchievementsPanel() {
  const achievements = useQuery({ queryKey: ["achievements"], queryFn: getAchievements });

  // Defensive: a partial response must not take the whole sheet down with it.
  const { earned = 0, total = 0, items = [], rarest = [] } = achievements.data ?? {};

  return (
    <SheetPanel
      title="Achievements"
      summary={`${earned} of ${total} earned`}
      className="h-[19rem]"
    >
      {/* The bragging rights, across the top. `rarest_held` already returns the
          five rarest, sorted — nothing to compute here. */}
      <div className="mb-2 grid shrink-0 grid-cols-5 gap-1">
        {Array.from({ length: 5 }, (_, index) => rarest[index]).map((row, index) => (
          <RarestCard key={row?.id ?? `empty-${index}`} row={row} />
        ))}
      </div>

      <FilteredList
        items={items}
        listLabel="Achievements"
        searchLabel="Search achievements"
        searchHint="Only achievements you have earned can be found by name."
        filters={[
          {
            id: "earned",
            label: "All",
            options: [
              { value: "yes", label: "Earned" },
              { value: "no", label: "Not yet" },
            ],
          },
        ]}
        match={(row, { term, values }) => {
          if (values.earned === "yes" && !row.earned) return false;
          if (values.earned === "no" && row.earned) return false;
          if (term) return row.earned && (row.name ?? "").toLowerCase().includes(term);
          return true;
        }}
        rowKey={(row) => row.id}
        empty="None yet. There are plenty waiting to be found."
        renderRow={(row) => <Row row={row} />}
      />
    </SheetPanel>
  );
}

/** Always five slots, filled or not — the row must not change width or height
 *  as the player's rarest five change (§2.1). */
function RarestCard({ row }: { row: AchievementRow | undefined }) {
  if (!row) {
    return (
      <div
        className="flex h-12 items-center justify-center rounded border border-dashed border-border text-content-faint"
        title="Nothing here yet"
      >
        <span aria-hidden>☆</span>
        <span className="sr-only">An empty slot for a rare achievement</span>
      </div>
    );
  }

  return (
    <div
      title={row.description ?? undefined}
      className="flex h-12 flex-col justify-center overflow-hidden rounded border border-accent-strong bg-accent/10 px-1.5 text-center"
    >
      <span className="truncate text-[11px] font-semibold leading-tight">{row.name}</span>
      <span className="text-[10px] text-content-muted tabular-nums">
        {formatRarity(row.rarity)}
      </span>
    </div>
  );
}

function Row({ row }: { row: AchievementRow }) {
  if (!row.earned) {
    return (
      <div className="flex items-center justify-between gap-2 px-1 py-1.5">
        <span className="select-none text-sm blur-[3px]" aria-hidden>
          Undiscovered achievement
        </span>
        <span className="sr-only">Undiscovered achievement</span>
        <span className="text-xs text-content-muted">—</span>
      </div>
    );
  }

  return (
    <div className="px-1 py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium">{row.name}</p>
        <span className="shrink-0 text-xs text-content-muted tabular-nums">
          {formatRarity(row.rarity)}
        </span>
      </div>
      <p className="truncate text-xs text-content-muted">{row.description}</p>
    </div>
  );
}
