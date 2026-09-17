import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  setChallengeState,
  updateChallenge,
  type AdminChallengeSummary,
  type ZoneSummary,
} from "../api/adminChallenges";
import type { ChallengeState, Difficulty } from "../api/challenges";

/**
 * The challenge list at 242 (spec 041).
 *
 * Three things make this different from the list it replaces. It is **grouped by
 * zone**, with each header carrying what an admin would otherwise work out by
 * hand — how much of the area exists, what it is worth against the 1,900 budget,
 * whether it has a boss. Its rows are **dense**, so the counts that say "this one
 * is unfinished" can be scanned rather than opened. And difficulty, XP and state
 * are **edited in place**, because setting an event up is mostly passes over a
 * whole area and none of those should cost a drawer and a save.
 */

const DIFFICULTIES: Difficulty[] = [
  "very_easy",
  "easy",
  "medium",
  "hard",
  "very_hard",
  "nearly_impossible",
];

const STATES: ChallengeState[] = ["draft", "hidden", "locked", "published"];

/** What a zone is expected to total, per the 018 economy. */
export const ZONE_XP_BUDGET = 1900;
/** The template's eleven-row spread (spec 026). A guide, not a limit. */
export const ZONE_EXPECTED_ROWS = 11;

const STATE_DOT: Record<ChallengeState, string> = {
  draft: "bg-surface-sunken",
  hidden: "bg-surface-sunken",
  locked: "bg-accent/60",
  published: "bg-moss",
};

export default function ChallengeTable({
  challenges,
  zones,
  canWrite,
  selected,
  onSelectedChange,
  openId,
  onOpen,
  collapsed,
  onToggleZone,
}: {
  challenges: AdminChallengeSummary[];
  zones: ZoneSummary[];
  canWrite: boolean;
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  openId: string | null;
  onOpen: (id: string) => void;
  collapsed: Set<string>;
  onToggleZone: (slug: string) => void;
}) {
  // Shift-click needs to know where the last plain click landed, and the answer
  // is per-render-order rather than per-zone: the rows the admin can see are the
  // range they mean.
  const [anchor, setAnchor] = useState<string | null>(null);

  const ordered = orderByZone(challenges, zones);
  const flat = ordered.flatMap(([, rows]) => rows.map((r) => r.id));

  const toggle = (id: string, shift: boolean) => {
    const next = new Set(selected);
    if (shift && anchor) {
      const from = flat.indexOf(anchor);
      const to = flat.indexOf(id);
      if (from !== -1 && to !== -1) {
        const [lo, hi] = from < to ? [from, to] : [to, from];
        for (const rowId of flat.slice(lo, hi + 1)) next.add(rowId);
        onSelectedChange(next);
        return;
      }
    }
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setAnchor(id);
    onSelectedChange(next);
  };

  const toggleZone = (rows: AdminChallengeSummary[]) => {
    const next = new Set(selected);
    const all = rows.every((r) => next.has(r.id));
    for (const row of rows) {
      if (all) next.delete(row.id);
      else next.add(row.id);
    }
    onSelectedChange(next);
  };

  if (challenges.length === 0) {
    return (
      <p className="mt-8 rounded border border-border bg-surface-raised px-4 py-6 text-center text-content-muted">
        Nothing matches.
      </p>
    );
  }

  return (
    <div className="mt-4">
      {ordered.map(([zone, rows]) => {
        const isCollapsed = collapsed.has(zone.slug);
        return (
          <section key={zone.category_id} className="mb-3">
            <ZoneHeader
              zone={zone}
              rows={rows}
              collapsed={isCollapsed}
              onToggle={() => onToggleZone(zone.slug)}
              canWrite={canWrite}
              allSelected={rows.length > 0 && rows.every((r) => selected.has(r.id))}
              someSelected={rows.some((r) => selected.has(r.id))}
              onToggleAll={() => toggleZone(rows)}
            />
            {!isCollapsed && (
              <table className="w-full border-collapse text-sm">
                <tbody>
                  {rows.map((challenge) => (
                    <Row
                      key={challenge.id}
                      challenge={challenge}
                      canWrite={canWrite}
                      selected={selected.has(challenge.id)}
                      onToggle={(shift) => toggle(challenge.id, shift)}
                      open={openId === challenge.id}
                      onOpen={() => onOpen(challenge.id)}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </section>
        );
      })}
    </div>
  );
}

/**
 * Zones in dungeon order, each with its own rows. A zone the current filter
 * emptied is dropped entirely rather than rendered as a header over nothing.
 */
function orderByZone(
  challenges: AdminChallengeSummary[],
  zones: ZoneSummary[],
): [ZoneSummary, AdminChallengeSummary[]][] {
  const byCategory = new Map<string, AdminChallengeSummary[]>();
  for (const challenge of challenges) {
    const list = byCategory.get(challenge.category.id) ?? [];
    list.push(challenge);
    byCategory.set(challenge.category.id, list);
  }
  return zones
    .filter((zone) => byCategory.has(zone.category_id))
    .map(
      (zone) =>
        [zone, byCategory.get(zone.category_id) ?? []] as [
          ZoneSummary,
          AdminChallengeSummary[],
        ],
    );
}

/**
 * The header earns its space: the XP total is the one place a zone that has
 * drifted off its budget becomes visible, now that spec 040 lets each challenge
 * carry its own value.
 */
function ZoneHeader({
  zone,
  rows,
  collapsed,
  onToggle,
  canWrite,
  allSelected,
  someSelected,
  onToggleAll,
}: {
  zone: ZoneSummary;
  rows: AdminChallengeSummary[];
  collapsed: boolean;
  onToggle: () => void;
  canWrite: boolean;
  allSelected: boolean;
  someSelected: boolean;
  onToggleAll: () => void;
}) {
  const offBudget = zone.total_xp !== ZONE_XP_BUDGET;
  return (
    <div className="flex items-center gap-2 rounded-t border border-border bg-surface-raised px-3 py-2">
      {canWrite && (
        <input
          type="checkbox"
          checked={allSelected}
          ref={(el) => {
            if (el) el.indeterminate = someSelected && !allSelected;
          }}
          onChange={onToggleAll}
          aria-label={`Select all in ${zone.name}`}
        />
      )}
      <button
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="flex flex-1 items-baseline gap-3 text-left"
      >
        <span aria-hidden>{collapsed ? "▶" : "▼"}</span>
        <span className="font-semibold">{zone.name}</span>
        <span className="text-xs text-content-muted">
          {zone.challenge_count}/{ZONE_EXPECTED_ROWS} written
        </span>
        <span
          className={`text-xs ${offBudget ? "text-warning" : "text-content-muted"}`}
          title={`The 018 economy budgets ${ZONE_XP_BUDGET} XP per area`}
        >
          {zone.total_xp.toLocaleString()}/{ZONE_XP_BUDGET.toLocaleString()} XP
        </span>
        {zone.boss_challenge_id ? (
          <span className="text-xs text-content-muted">★ {zone.boss_tier}</span>
        ) : (
          <span className="text-xs text-warning">no boss</span>
        )}
        {zone.draft_count > 0 && (
          <span className="text-xs text-content-muted">{zone.draft_count} draft</span>
        )}
      </button>
      <span className="text-xs text-content-muted">{rows.length} shown</span>
    </div>
  );
}

function Row({
  challenge,
  canWrite,
  selected,
  onToggle,
  open,
  onOpen,
}: {
  challenge: AdminChallengeSummary;
  canWrite: boolean;
  selected: boolean;
  onToggle: (shift: boolean) => void;
  open: boolean;
  onOpen: () => void;
}) {
  const queryClient = useQueryClient();
  // Optimistic locally so a select does not flicker back while the round trip
  // is in flight; the invalidate below is what makes it true.
  const [draft, setDraft] = useState<{
    difficulty?: Difficulty;
    state?: ChallengeState;
    xp?: string;
  }>({});

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "challenges"] });
    await queryClient.invalidateQueries({ queryKey: ["admin", "zones"] });
  };

  const save = useMutation({
    mutationFn: (patch: Parameters<typeof updateChallenge>[1]) =>
      updateChallenge(challenge.id, patch),
    onSuccess: refresh,
  });

  // State has its own endpoint rather than riding on the patch: it is audited
  // separately, and pulling a challenge is the decision someone asks about later.
  const changeState = useMutation({
    mutationFn: (state: ChallengeState) => setChallengeState(challenge.id, state),
    onSuccess: refresh,
  });

  const difficulty = draft.difficulty ?? challenge.difficulty;
  const state = draft.state ?? challenge.state;
  const xp = draft.xp ?? String(challenge.initial_points);

  return (
    <tr
      className={`border-b border-border/40 ${open ? "bg-surface" : "hover:bg-surface-raised"}`}
    >
      {canWrite && (
        <td className="w-8 px-3 py-1">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Select ${challenge.title}`}
            onChange={() => undefined}
            onClick={(e) => onToggle(e.shiftKey)}
          />
        </td>
      )}
      <td className="py-1">
        <button onClick={onOpen} className="text-left hover:underline">
          {challenge.title}
        </button>
        {challenge.boss_tier && (
          <span className="ml-2 text-xs text-accent-strong" title={`${challenge.boss_tier} boss`}>
            ★
          </span>
        )}
        {challenge.ai_ladder_level !== null && (
          <span className="ml-1 text-xs text-content-muted" title="System AI ladder rung">
            L{challenge.ai_ladder_level}
          </span>
        )}
      </td>
      <td className="w-40 py-1">
        <select
          value={difficulty}
          disabled={!canWrite || save.isPending}
          onChange={(e) => {
            const value = e.target.value as Difficulty;
            setDraft((d) => ({ ...d, difficulty: value }));
            // Deliberately alone: difficulty is a label and does not move XP.
            save.mutate({ difficulty: value });
          }}
          className="w-full rounded border border-border/60 bg-transparent px-1 py-0.5 text-xs"
        >
          {DIFFICULTIES.map((d) => (
            <option key={d} value={d}>
              {d.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </td>
      <td className="w-20 py-1">
        <input
          type="number"
          min={1}
          value={xp}
          disabled={!canWrite || save.isPending}
          aria-label={`XP for ${challenge.title}`}
          onChange={(e) => setDraft((d) => ({ ...d, xp: e.target.value }))}
          onBlur={() => {
            const value = Number(xp);
            if (value >= 1 && value !== challenge.initial_points) {
              save.mutate({ initial_points: value });
            }
          }}
          className="w-full rounded border border-border/60 bg-transparent px-1 py-0.5 text-right text-xs tabular-nums"
        />
      </td>
      <td className="w-28 py-1">
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2 w-2 rounded-full ${STATE_DOT[state]}`} />
          <select
            value={state}
            disabled={!canWrite || changeState.isPending}
            aria-label={`State for ${challenge.title}`}
            onChange={(e) => {
              const value = e.target.value as ChallengeState;
              setDraft((d) => ({ ...d, state: value }));
              changeState.mutate(value);
            }}
            className="w-full rounded border border-border/60 bg-transparent px-1 py-0.5 text-xs"
          >
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </span>
      </td>
      {/* A zero is the signal: no flag means nobody can solve it, no skills
          means its XP lands on no character sheet. */}
      <Count value={challenge.answer_count} label="flags" warn />
      <Count value={challenge.hint_count} label="hints" />
      <Count value={challenge.skill_count} label="skills" warn />
      <td className="w-16 py-1 pr-3 text-right text-xs tabular-nums text-content-muted">
        {challenge.solve_count}
      </td>
    </tr>
  );
}

function Count({
  value,
  label,
  warn = false,
}: {
  value: number;
  label: string;
  warn?: boolean;
}) {
  return (
    <td
      className={`w-10 py-1 text-center text-xs tabular-nums ${
        value === 0 && warn ? "text-warning" : "text-content-muted"
      }`}
      title={`${value} ${label}`}
    >
      {value}
    </td>
  );
}
