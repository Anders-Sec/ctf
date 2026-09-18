import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { listChallenges } from "../api/challenges";
import { getTeamProgress } from "../api/teams";
import ErrorMessage from "./ErrorMessage";

/**
 * Where the party has been, and where it has not (spec 067 §2.1).
 *
 * This is the point of the page. Spec 005 scores a challenge **once per party**
 * however many members solve it — *"size buys speed and coverage, never a higher
 * ceiling"* — so two members on the same challenge is wasted effort, and until
 * now nothing said so.
 *
 * The bar moves when *anybody* clears something, which is exactly what the
 * scoring does. Opening a zone names who claimed each challenge, which is the
 * coordination fix stated as plainly as it can be: **Rin has this one; it will
 * not pay twice.** It is not a lock and not a claim system — it shows what the
 * scoring already decided.
 */
export default function PartyCoverage({ teamId }: { teamId: string }) {
  const progress = useQuery({
    queryKey: ["team", teamId, "progress"],
    queryFn: () => getTeamProgress(teamId),
  });
  // The titles. Coverage counts on the server; the names come from the board a
  // member can already see, so nothing new is exposed by listing them here.
  const challenges = useQuery({ queryKey: ["challenges"], queryFn: listChallenges });
  const [open, setOpen] = useState<string | null>(null);

  if (progress.isError) return <ErrorMessage error={progress.error} />;
  const zones = progress.data?.zones ?? [];
  const solvedBy = progress.data?.solved_by ?? {};

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Coverage
        </h2>
        <span className="text-xs text-content-muted">
          A challenge counts once, however many of you solve it.
        </span>
      </div>

      {zones.length === 0 ? (
        <p className="mt-3 text-sm text-content-muted">Nothing unsealed yet.</p>
      ) : (
        <ul className="mt-3 flex flex-col">
          {zones.map((zone) => {
            const percent = zone.total > 0 ? (zone.cleared / zone.total) * 100 : 0;
            const expanded = open === zone.slug;
            const inZone = (challenges.data ?? []).filter(
              (row) => row.category.slug === zone.slug,
            );

            return (
              <li key={zone.slug} className="border-b border-border last:border-0">
                <button
                  type="button"
                  onClick={() => setOpen(expanded ? null : zone.slug)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-3 py-2 text-left text-sm hover:bg-surface-raised"
                >
                  <span aria-hidden className="w-3 shrink-0 text-content-muted">
                    {expanded ? "▾" : "▸"}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {zone.sealed && <span aria-label="Sealed">🔒 </span>}
                    {zone.name}
                  </span>
                  <span
                    aria-hidden
                    className="hidden h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-surface-sunken sm:block"
                  >
                    <span
                      className="block h-full bg-accent-strong"
                      style={{ width: `${percent}%` }}
                    />
                  </span>
                  <span className="w-14 shrink-0 text-right text-xs text-content-muted tabular-nums">
                    {zone.cleared}/{zone.total}
                  </span>
                </button>

                {expanded && (
                  <ul className="pb-2 pl-6">
                    {inZone.length === 0 ? (
                      <li className="py-1 text-xs text-content-muted">
                        Nothing here you can see yet.
                      </li>
                    ) : (
                      inZone.map((row) => {
                        const who = solvedBy[row.id];
                        return (
                          <li
                            key={row.id}
                            className="flex items-center gap-2 py-1 text-sm"
                          >
                            <span
                              aria-hidden
                              className={who ? "text-success" : "text-content-faint"}
                            >
                              {who ? "✓" : "○"}
                            </span>
                            <span className="min-w-0 flex-1 truncate">
                              {row.locked || row.title === null ? (
                                <span className="text-content-muted">Sealed</span>
                              ) : (
                                <Link to={`/challenges/${row.id}`} className="hover:underline">
                                  {row.title}
                                </Link>
                              )}
                            </span>
                            {/* "Ask Rin how they did it" is the point (§7.2). */}
                            <span className="shrink-0 text-xs text-content-muted">
                              {who ?? ""}
                            </span>
                          </li>
                        );
                      })
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
