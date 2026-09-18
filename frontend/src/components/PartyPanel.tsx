import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { Link } from "react-router-dom";

import { getPartyPanel } from "../api/scoreboard";
import { useDialogFocus } from "../hooks/useDialogFocus";
import Avatar from "./Avatar";
import { BossStarBreakdown } from "./BossStars";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";
import { RARITY_TEXT } from "./classRarity";

/**
 * Who a party is (spec 059 §5).
 *
 * Reached from both boards — a party row, or the Party column on the player
 * board. A panel rather than a page: a party has no route of its own and does
 * not need one, and what a player wants here is a glance at who is in it.
 *
 * **No XP, member XP included.** A per-member XP list would be the scoreboard's
 * worst habit reintroduced one level down.
 */
export default function PartyPanel({
  teamId,
  onClose,
}: {
  teamId: string;
  onClose: () => void;
}) {
  const panel = useQuery({
    queryKey: ["scoreboard", "party", teamId],
    queryFn: () => getPartyPanel(teamId),
  });

  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog, { onClose });

  const data = panel.data;

  return (
    <>
      <div className="fixed inset-0 z-30 bg-content/20" onClick={onClose} aria-hidden />
      <aside
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Party detail"
        className="fixed inset-y-0 right-0 z-40 w-full max-w-sm overflow-y-auto border-l border-border-strong bg-surface-overlay p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-xl font-semibold">{data?.name ?? "Party"}</h2>
            {data && (
              <p className="mt-0.5 text-sm text-content-muted">
                Rank {data.rank} · Level {data.level}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close party detail"
            className="shrink-0 text-xl leading-none"
          >
            ×
          </button>
        </div>

        {panel.isPending && <Spinner label="Reading the roll…" />}
        <ErrorMessage error={panel.error} />

        {data && (
          <>
            <dl className="mt-5 grid grid-cols-3 gap-3 text-center">
              <Stat label="Solved" value={data.solve_count} />
              <Stat label="Awards" value={data.achievement_count} />
              <Stat label="Adventurers" value={data.member_count} />
            </dl>

            <section className="mt-6">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
                Bosses felled
              </h3>
              <div className="mt-2">
                <BossStarBreakdown stars={data.stars} />
              </div>
            </section>

            <section className="mt-6">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
                The party
              </h3>
              {data.members.length === 0 ? (
                <p className="mt-2 text-sm text-content-muted">Nobody in it yet.</p>
              ) : (
                <ul className="mt-2 flex flex-col">
                  {data.members.map((member) => (
                    <li key={member.user_id} className="border-b border-border py-1.5 last:border-0">
                      <Link
                        to={`/character/${member.user_id}`}
                        className="flex items-center gap-2 hover:underline"
                      >
                        <Avatar
                          userId={member.user_id}
                          displayName={member.display_name}
                          size={24}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm">{member.display_name}</span>
                          {member.class_name && (
                            <span
                              className={`block truncate text-xs ${RARITY_TEXT[member.class_rarity ?? ""] ?? "text-content-muted"}`}
                            >
                              {member.class_name}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-xs text-content-muted tabular-nums">
                          Lv {member.level}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <p className="mt-6 text-xs text-content-faint">
              Founded {new Date(data.founded_at).toLocaleDateString()}
            </p>
          </>
        )}
      </aside>
    </>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-border bg-surface-raised py-2">
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      <dt className="text-xs text-content-muted">{label}</dt>
    </div>
  );
}
