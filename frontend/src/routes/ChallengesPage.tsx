import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";

import {
  DIFFICULTY_LABEL,
  getMyScore,
  listChallenges,
  type ChallengeListItem,
} from "../api/challenges";
import { getMap } from "../api/dungeon";
import { KIND_LABEL } from "../api/puzzles";
import DungeonMap from "../components/DungeonMap";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

type View = "map" | "list";

const VIEW_KEY = "ctf.challenges.view";
const CLOSED_KEY = "ctf.challenges.closed";

/**
 * The challenge board (specs 017, 062).
 *
 * **The list is the board now.** It opens here and the map is one toggle away,
 * untouched, for a later pass.
 *
 * The detail opens as an overlay through `<Outlet />` rather than as a page of
 * its own, so this list never unmounts — scroll position survives by
 * construction rather than by saving and restoring it, which is the class of bug
 * that is easy to write and easy to get subtly wrong.
 *
 * Ordering is the server's (zone → difficulty → authored price) and is
 * deliberately left alone here. Sorting on the live value would reshuffle the
 * board under a player as the decay ran.
 */
function storedView(): View {
  try {
    // The list is the default since spec 062; only an explicit choice of the
    // map wins, so an old stored "list" and a fresh browser agree.
    return localStorage.getItem(VIEW_KEY) === "map" ? "map" : "list";
  } catch {
    return "list";
  }
}

export default function ChallengesPage() {
  const [view, setView] = useState<View>(storedView);
  const [search, setSearch] = useState("");
  const [hideSolved, setHideSolved] = useState(false);
  const [drawer, setDrawer] = useState(false);

  const challenges = useQuery({ queryKey: ["challenges"], queryFn: listChallenges });
  const score = useQuery({ queryKey: ["my-score"], queryFn: getMyScore });
  const map = useQuery({ queryKey: ["map"], queryFn: getMap, enabled: view === "map" });

  const chooseView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Not worth failing the click over.
    }
  };

  const rows = challenges.data ?? [];
  const zones = useMemo(() => groupIntoZones(rows), [rows]);

  const term = search.trim().toLowerCase();
  const shown = useMemo(
    () =>
      zones
        .map((zone) => ({
          ...zone,
          challenges: zone.challenges.filter((row) => {
            if (hideSolved && row.solved) return false;
            // A sealed row has no name, so it cannot match a search — the same
            // reason an undiscovered skill cannot (spec 060).
            if (term) return (row.title ?? "").toLowerCase().includes(term);
            return true;
          }),
        }))
        .filter((zone) => zone.challenges.length > 0 || (zone.sealed && !term && !hideSolved)),
    [zones, term, hideSolved],
  );

  if (challenges.isPending) return <Spinner label="Lighting the torches…" />;
  if (challenges.isError) return <ErrorMessage error={challenges.error} />;

  const solved = rows.filter((row) => row.solved).length;

  return (
    <main className="mx-auto max-w-6xl p-4 sm:p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Challenges</h1>
          <p className="mt-1 text-content-muted">
            {solved} of {rows.length} cleared
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-1" role="group" aria-label="Board view">
            {(
              [
                ["list", "List"],
                ["map", "Map"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                onClick={() => chooseView(value)}
                aria-pressed={view === value}
                className={`rounded px-3 py-1.5 text-sm ${
                  view === value ? "bg-content text-surface" : "border border-border"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-2xl font-semibold" aria-label="Your XP">
            {score.data?.total ?? 0}
            <span className="ml-1 text-sm font-normal text-content-muted">points</span>
          </p>
        </div>
      </header>

      {view === "map" ? (
        <>
          {map.isPending && <Spinner label="Drawing the map…" />}
          <ErrorMessage error={map.error} />
          {map.data && <DungeonMap data={map.data} fullBleed />}
        </>
      ) : (
        <div className="mt-5 flex gap-6">
          <ZoneSidebar zones={zones} open={drawer} onClose={() => setDrawer(false)} />

          {/* A landmark of its own, so a reader can skip past the zone nav
              rather than walking 21 links to reach the board. */}
          <section aria-label="Challenge board" className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setDrawer(true)}
                className="rounded border border-border px-3 py-1.5 text-sm lg:hidden"
              >
                Zones
              </button>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search challenges"
                aria-label="Search challenges"
                className="min-w-40 flex-1 rounded border border-border-strong bg-surface-raised px-2 py-1.5 text-sm"
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={hideSolved}
                  onChange={(event) => setHideSolved(event.target.checked)}
                />
                Hide solved
              </label>
            </div>

            {shown.length === 0 ? (
              <p className="mt-8 text-content-muted">
                {term || hideSolved
                  ? "Nothing matches that."
                  : "Nothing has been unsealed yet. Check back when the next wave opens."}
              </p>
            ) : (
              shown.map((zone) => <ZoneGroup key={zone.slug} zone={zone} />)
            )}
          </section>
        </div>
      )}

      {/* The overlay. The board above stays mounted behind it. */}
      <Outlet />
    </main>
  );
}

export interface Zone {
  slug: string;
  name: string;
  order: number;
  challenges: ChallengeListItem[];
  cleared: number;
  total: number;
  /** Every challenge in it is locked, so it collapses to one row (§4.1). */
  sealed: boolean;
  /** The carrot on a sealed zone: what is in there, without saying what. */
  xpTotal: number;
}

/**
 * Groups the server's already-ordered list, preserving that order.
 *
 * A "sealed zone" is derived rather than a new gate: spec 019's percent-of-zone
 * requirements already do that work, and a zone whose every challenge is locked
 * is exactly what one looks like from here.
 */
export function groupIntoZones(rows: ChallengeListItem[]): Zone[] {
  const zones = new Map<string, Zone>();
  for (const row of rows) {
    const existing = zones.get(row.category.slug);
    const zone = existing ?? {
      slug: row.category.slug,
      name: row.category.name,
      order: row.category.display_order,
      challenges: [],
      cleared: 0,
      total: 0,
      sealed: true,
      xpTotal: 0,
    };
    zone.challenges.push(row);
    zone.total += 1;
    zone.xpTotal += row.value;
    if (row.solved) zone.cleared += 1;
    if (!row.locked) zone.sealed = false;
    if (!existing) zones.set(row.category.slug, zone);
  }
  return [...zones.values()].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name));
}

function ZoneSidebar({
  zones,
  open,
  onClose,
}: {
  zones: Zone[];
  open: boolean;
  onClose: () => void;
}) {
  const jump = (slug: string) => {
    document.getElementById(`zone-${slug}`)?.scrollIntoView({ behavior: "smooth" });
    onClose();
  };

  const list = (
    <ul className="flex flex-col">
      {zones.map((zone) => (
        <li key={zone.slug}>
          <button
            type="button"
            onClick={() => jump(zone.slug)}
            className="flex w-full items-baseline justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-surface-raised"
          >
            <span className="min-w-0 truncate">
              {zone.sealed && <span aria-label="Sealed">🔒 </span>}
              {zone.name}
            </span>
            {/* Not decoration: spec 019 gates zones on the percent cleared, so
                this is the number a player would otherwise count by hand. */}
            <span className="shrink-0 text-xs text-content-muted tabular-nums">
              {zone.cleared}/{zone.total}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <>
      <nav aria-label="Zones" className="sticky top-4 hidden h-fit w-56 shrink-0 lg:block">
        <h2 className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-content-muted">
          Zones
        </h2>
        {list}
      </nav>

      {open && (
        <>
          <div className="fixed inset-0 z-30 bg-content/30 lg:hidden" onClick={onClose} aria-hidden />
          <nav
            aria-label="Zones"
            className="fixed inset-y-0 left-0 z-40 w-64 overflow-y-auto border-r border-border-strong bg-surface-overlay p-4 lg:hidden"
          >
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-content-muted">
                Zones
              </h2>
              <button type="button" onClick={onClose} aria-label="Close zones" className="text-xl leading-none">
                ×
              </button>
            </div>
            {list}
          </nav>
        </>
      )}
    </>
  );
}

function readClosed(): Set<string> {
  try {
    const raw = localStorage.getItem(CLOSED_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function ZoneGroup({ zone }: { zone: Zone }) {
  const [closed, setClosed] = useState(() => readClosed().has(zone.slug));

  const toggle = () => {
    const next = !closed;
    setClosed(next);
    try {
      const set = readClosed();
      if (next) set.add(zone.slug);
      else set.delete(zone.slug);
      localStorage.setItem(CLOSED_KEY, JSON.stringify([...set]));
    } catch {
      // A collapse we cannot remember still collapses.
    }
  };

  // A sealed zone is one row. No per-challenge rows at all — the size is the
  // carrot, and it gives away nothing about what is in there (§4.1).
  if (zone.sealed) {
    return (
      <section id={`zone-${zone.slug}`} className="mt-4 rounded-lg border border-accent/40 bg-accent/5 p-4">
        <h2 className="font-medium">
          <span aria-label="Sealed">🔒</span> {zone.name}
        </h2>
        <Requirements challenges={zone.challenges} />
        <p className="mt-2 text-sm text-content-muted tabular-nums">
          {zone.total} {zone.total === 1 ? "challenge" : "challenges"} ·{" "}
          {zone.xpTotal.toLocaleString()} XP
        </p>
      </section>
    );
  }

  return (
    <section id={`zone-${zone.slug}`} className="mt-4">
      <h2 className="sticky top-0 z-10 bg-surface">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!closed}
          className="flex w-full items-baseline gap-2 border-b border-border-strong px-1 py-1.5 text-left"
        >
          <span aria-hidden className="w-3 text-content-muted">
            {closed ? "▸" : "▾"}
          </span>
          <span className="font-semibold">{zone.name}</span>
          {/* A shut group still says what is inside it. */}
          <span className="ml-auto text-xs text-content-muted tabular-nums">
            {zone.cleared}/{zone.total}
          </span>
        </button>
      </h2>
      {!closed && (
        <ul>
          {zone.challenges.map((challenge) => (
            <ChallengeRow key={challenge.id} challenge={challenge} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** Server-rendered descriptions, so every gate type reads the same (spec 017). */
function Requirements({ challenges }: { challenges: ChallengeListItem[] }) {
  const seen = new Map<string, { description: string; met: boolean; progress: string | null }>();
  for (const challenge of challenges) {
    for (const requirement of challenge.unlock_requirements) {
      if (seen.has(requirement.description)) continue;
      seen.set(requirement.description, {
        description: requirement.description,
        met: requirement.met,
        progress:
          requirement.threshold !== null && requirement.progress !== null
            ? `${requirement.progress}/${requirement.threshold}`
            : null,
      });
    }
  }

  if (seen.size === 0) {
    return <p className="mt-1 text-sm text-content-muted">Not open yet.</p>;
  }

  return (
    <ul className="mt-1 flex flex-col gap-0.5 text-sm">
      {[...seen.values()].map((requirement) => (
        <li key={requirement.description}>
          <span aria-hidden>{requirement.met ? "✓" : "•"}</span> {requirement.description}
          {requirement.progress && (
            <span className="ml-1 text-content-muted tabular-nums">({requirement.progress})</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function ChallengeRow({ challenge }: { challenge: ChallengeListItem }) {
  const navigate = useNavigate();

  const meta = (
    <>
      <span className="w-16 shrink-0 text-right text-sm tabular-nums">{challenge.value}</span>
      <span className="hidden w-32 shrink-0 text-right text-sm text-content-muted sm:block">
        {DIFFICULTY_LABEL[challenge.difficulty]}
      </span>
    </>
  );

  if (challenge.locked) {
    return (
      <li className="border-b border-border px-1 py-1.5">
        <div className="flex items-center gap-3">
          <span aria-hidden className="w-4 shrink-0 text-center">
            🔒
          </span>
          {/* No name: the server did not send one. The blur is the shape of a
              title, not a title anybody could read (§4.2). */}
          <span
            aria-hidden
            className="min-w-0 flex-1 select-none truncate text-sm blur-[3px]"
          >
            ████████████
          </span>
          <span className="sr-only">A sealed challenge</span>
          {meta}
        </div>
        <div className="pl-7 text-xs text-content-muted">
          <Requirements challenges={[challenge]} />
        </div>
      </li>
    );
  }

  return (
    <li className="border-b border-border">
      <button
        type="button"
        onClick={() => navigate(`/challenges/${challenge.id}`)}
        className={`flex w-full items-center gap-3 px-1 py-1.5 text-left hover:bg-surface-raised ${
          challenge.solved ? "text-content-muted" : ""
        }`}
      >
        <span aria-hidden className="w-4 shrink-0 text-center text-sm">
          {challenge.solved ? "✓" : challenge.puzzle_status === "failed" ? "✗" : ""}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">
          {challenge.title}
          {/* "This is a Wordle, not a flag hunt" changes how a player
              approaches a row, so it earns its width (spec 062 §2.2). */}
          {challenge.puzzle_kind && (
            <span className="ml-2 rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
              {KIND_LABEL[challenge.puzzle_kind]}
            </span>
          )}
          {challenge.max_attempts !== null && (
            <span className="ml-2 text-xs text-content-muted">
              {challenge.attempts_remaining} of {challenge.max_attempts} left
            </span>
          )}
        </span>
        {meta}
      </button>
    </li>
  );
}
