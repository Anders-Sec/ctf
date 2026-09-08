import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getMyScore, listChallenges, type ChallengeListItem } from "../api/challenges";
import { getMap } from "../api/dungeon";
import DungeonMap from "../components/DungeonMap";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

type View = "map" | "list";

const VIEW_KEY = "ctf.challenges.view";

/** Remembered per browser. A stored preference is a convenience, so a private
 *  window or blocked storage just falls back to the default. */
function storedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "map";
  } catch {
    return "map";
  }
}

/** The challenge board (spec 017). Opens on the dungeon map; the list is one
 *  toggle away and stays a complete equivalent — it is what people use to scan
 *  and filter a few hundred challenges, and it is the accessible fallback. */
export default function ChallengesPage() {
  const [category, setCategory] = useState<string | null>(null);
  const [hideSolved, setHideSolved] = useState(false);
  const [view, setView] = useState<View>(storedView);

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

  const grouped = useMemo(() => {
    const rows = (challenges.data ?? [])
      .filter((c) => (category ? c.category.slug === category : true))
      .filter((c) => (hideSolved ? !c.solved : true));

    const byCategory = new Map<string, ChallengeListItem[]>();
    for (const row of rows) {
      const key = row.category.name;
      byCategory.set(key, [...(byCategory.get(key) ?? []), row]);
    }
    return [...byCategory.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [challenges.data, category, hideSolved]);

  const categories = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of challenges.data ?? []) seen.set(row.category.slug, row.category.name);
    return [...seen.entries()];
  }, [challenges.data]);

  if (challenges.isPending) return <Spinner label="Lighting the torches…" />;
  if (challenges.isError) return <ErrorMessage error={challenges.error} />;

  const rows = challenges.data ?? [];
  const solved = rows.filter((r) => r.solved).length;

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Challenges</h1>
          <p className="mt-1 text-muted">
            {solved} of {rows.length} cleared
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-1" role="group" aria-label="Board view">
            {(
              [
                ["map", "Map"],
                ["list", "List"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                onClick={() => chooseView(value)}
                aria-pressed={view === value}
                className={`rounded px-3 py-1.5 text-sm ${
                  view === value ? "bg-ink text-parchment" : "border border-stone"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-2xl font-semibold" aria-label="Your score">
            {score.data?.total ?? 0}
            <span className="ml-1 text-sm font-normal text-muted">points</span>
          </p>
        </div>
      </header>

      {view === "map" ? (
        <>
          {map.isPending && <Spinner label="Drawing the map…" />}
          <ErrorMessage error={map.error} />
          {map.data && <DungeonMap data={map.data} />}
        </>
      ) : (
        <ListView
          rows={rows}
          grouped={grouped}
          categories={categories}
          category={category}
          setCategory={setCategory}
          hideSolved={hideSolved}
          setHideSolved={setHideSolved}
        />
      )}
    </main>
  );
}

function ListView({
  rows,
  grouped,
  categories,
  category,
  setCategory,
  hideSolved,
  setHideSolved,
}: {
  rows: ChallengeListItem[];
  grouped: [string, ChallengeListItem[]][];
  categories: [string, string][];
  category: string | null;
  setCategory: (value: string | null) => void;
  hideSolved: boolean;
  setHideSolved: (value: boolean) => void;
}) {
  return (
    <>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setCategory(null)}
          className={`rounded px-3 py-1.5 text-sm ${
            category === null ? "bg-ink text-parchment" : "border border-stone"
          }`}
        >
          All
        </button>
        {categories.map(([slug, name]) => (
          <button
            key={slug}
            onClick={() => setCategory(slug)}
            className={`rounded px-3 py-1.5 text-sm ${
              category === slug ? "bg-ink text-parchment" : "border border-stone"
            }`}
          >
            {name}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={hideSolved}
            onChange={(event) => setHideSolved(event.target.checked)}
          />
          Hide solved
        </label>
      </div>

      {rows.length === 0 && (
        <p className="mt-8 text-muted">
          Nothing has been unsealed yet. Check back when the next wave opens.
        </p>
      )}

      {grouped.map(([name, items]) => (
        <section key={name} className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{name}</h2>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {items.map((challenge) => (
              <ChallengeCard key={challenge.id} challenge={challenge} />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

function ChallengeCard({ challenge }: { challenge: ChallengeListItem }) {
  const classes = [
    "rounded-lg border p-4 transition",
    challenge.solved ? "border-ink/40 bg-ink/5" : "border-stone bg-white/60",
    challenge.locked ? "opacity-70" : "hover:border-ink",
  ].join(" ");

  const inner = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span className="font-medium">
          {challenge.title}
          {challenge.solved && <span className="ml-2 text-sm text-muted">✓ solved</span>}
        </span>
        <span className="shrink-0 font-semibold">{challenge.value}</span>
      </div>
      <p className="mt-2 text-sm text-muted">
        {challenge.difficulty} · {challenge.solve_count}{" "}
        {challenge.solve_count === 1 ? "solve" : "solves"}
        {challenge.max_attempts !== null && (
          <> · {challenge.attempts_remaining} of {challenge.max_attempts} attempts left</>
        )}
      </p>
      {challenge.locked && (
        <p className="mt-2 text-sm text-torch">
          Sealed
          {challenge.release_at && ` until ${new Date(challenge.release_at).toLocaleString()}`}
        </p>
      )}
    </>
  );

  // A locked card is deliberately not a link: there is nothing behind it yet.
  return (
    <li>
      {challenge.locked ? (
        <div className={classes}>{inner}</div>
      ) : (
        <Link to={`/challenges/${challenge.id}`} className={`block ${classes}`}>
          {inner}
        </Link>
      )}
    </li>
  );
}
