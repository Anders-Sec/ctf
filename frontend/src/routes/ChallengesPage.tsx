import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getMyScore, listChallenges, type ChallengeListItem } from "../api/challenges";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/** The challenge board. Grouped by category, locked entries shown but inert. */
export default function ChallengesPage() {
  const [category, setCategory] = useState<string | null>(null);
  const [hideSolved, setHideSolved] = useState(false);

  const challenges = useQuery({ queryKey: ["challenges"], queryFn: listChallenges });
  const score = useQuery({ queryKey: ["my-score"], queryFn: getMyScore });

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
        <p className="text-2xl font-semibold" aria-label="Your score">
          {score.data?.total ?? 0}
          <span className="ml-1 text-sm font-normal text-muted">points</span>
        </p>
      </header>

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
    </main>
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
