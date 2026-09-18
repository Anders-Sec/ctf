import { useQuery } from "@tanstack/react-query";

import { getPublicAchievements, type PublicAchievement } from "../../api/character";
import { formatRarity } from "./AchievementsPanel";
import { FilteredList, SheetPanel } from "./SheetPanel";

/**
 * Somebody else's achievements (spec 061 §4).
 *
 * **A trophy case, not a progress bar.** Only what they earned — their progress
 * is nobody else's business, so unearned rows are absent entirely rather than
 * listed as blanks the way the own sheet lists them.
 *
 * **No descriptions at all.** Worth being precise about why, because the obvious
 * reason is wrong: the text that says *how* to earn one is `earned_by`, and that
 * has never reached any player on any sheet. Dropping the flavour line costs a
 * little colour and removes a class of hint nobody has to reason about again.
 *
 * A row with a null name is a secret the viewer has not earned themselves. It is
 * **redacted on the server** — name and rarity both absent from the payload — so
 * the blur here is honest and there is nothing to read in devtools. The row is
 * still present: a player's proudest finds should be visibly there, just
 * unreadable.
 */
export default function TrophyCasePanel({ userId }: { userId: string }) {
  const achievements = useQuery({
    queryKey: ["character", userId, "achievements"],
    queryFn: () => getPublicAchievements(userId),
  });

  const { earned = 0, secret_count = 0, items = [], rarest = [] } = achievements.data ?? {};

  return (
    <SheetPanel
      title="Achievements"
      summary={
        // Hidden at zero: a player who has found no secrets should not get a
        // line pointing that out (spec 061 §9.2).
        secret_count > 0 ? `${earned} earned · ${secret_count} secret` : `${earned} earned`
      }
      className="h-[19rem]"
    >
      {/* The five rarest the viewer can see *named*. Secrets are excluded even
          though they are usually the rarest a player holds — a case of five
          blurred squares brags about nothing and looks broken (§4.2). */}
      <div className="mb-2 grid shrink-0 grid-cols-5 gap-1">
        {Array.from({ length: 5 }, (_, index) => rarest[index]).map((row, index) => (
          <RarestCard key={row?.id ?? `empty-${index}`} row={row} />
        ))}
      </div>

      <FilteredList
        items={items}
        listLabel="Achievements"
        searchLabel="Search achievements"
        searchHint={secret_count > 0 ? "Secrets you have not found yourself stay hidden." : undefined}
        match={(row, { term }) => {
          if (!term) return true;
          // A redacted row has no name, so there is nothing to match — the same
          // reason an undiscovered skill cannot be searched.
          return (row.name ?? "").toLowerCase().includes(term);
        }}
        rowKey={(row) => row.id}
        empty="Nothing earned yet."
        renderRow={(row) => <Row row={row} />}
      />
    </SheetPanel>
  );
}

function RarestCard({ row }: { row: PublicAchievement | undefined }) {
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
    <div className="flex h-12 flex-col justify-center overflow-hidden rounded border border-accent-strong bg-accent/10 px-1.5 text-center">
      <span className="truncate text-[11px] font-semibold leading-tight">{row.name}</span>
      <span className="text-[10px] text-content-muted tabular-nums">
        {formatRarity(row.rarity)}
      </span>
    </div>
  );
}

function Row({ row }: { row: PublicAchievement }) {
  if (row.name === null) {
    return (
      <div className="flex items-center justify-between gap-2 px-1 py-1.5">
        {/* The same treatment the own sheet gives an unearned row, so a player
            has already learned what it means. */}
        <span className="select-none text-sm blur-[3px]" aria-hidden>
          A secret they found
        </span>
        <span className="sr-only">A secret achievement you have not found</span>
        <span className="text-xs text-content-muted">—</span>
      </div>
    );
  }

  return (
    <div className="flex items-baseline justify-between gap-2 px-1 py-1.5">
      <p className="min-w-0 truncate text-sm font-medium">{row.name}</p>
      <span className="shrink-0 text-xs text-content-muted tabular-nums">
        {formatRarity(row.rarity)}
      </span>
    </div>
  );
}
