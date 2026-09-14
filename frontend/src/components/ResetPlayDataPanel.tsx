import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  listPlayData,
  resetPlayData,
  type PlayDataGroup,
} from "../api/adminOps";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";

/**
 * Clearing an event's play data (spec 043).
 *
 * Setting an event up means playing it a bit, and that test play then pins the
 * challenges it touched — a solved challenge cannot be deleted. This is how it
 * is taken back.
 *
 * It is the one place in the admin tooling that earns real ceremony. Everything
 * else here is low-friction on purpose, because this page builds an event rather
 * than running one; this is a single irreversible action across a dozen tables
 * with no undo, and nothing on screen reveals its scale until the counts do.
 */
export default function ResetPlayDataPanel({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [typed, setTyped] = useState("");
  const [done, setDone] = useState<number | null>(null);

  const groups = useQuery({
    queryKey: ["admin", "play-data"],
    queryFn: listPlayData,
    enabled: canWrite,
  });

  const run = useMutation({
    mutationFn: () => resetPlayData([...chosen]),
    onSuccess: async (result) => {
      setDone(result.total);
      setChosen(new Set());
      setTyped("");
      await queryClient.invalidateQueries();
    },
  });

  if (!canWrite) return null;

  const rows = groups.data ?? [];
  const toggle = (group: string) => {
    const next = new Set(chosen);
    if (next.has(group)) next.delete(group);
    else next.add(group);
    setChosen(next);
    setDone(null);
  };

  const selectedRows = rows.filter((row) => chosen.has(row.group));
  const total = selectedRows.reduce((sum, row) => sum + row.rows, 0);
  const armed = chosen.size > 0 && typed === "RESET";

  return (
    <section className="mt-10 rounded border border-torch/50 bg-white/40 p-4">
      <h2 className="text-lg font-semibold">Reset play data</h2>
      <p className="mt-1 text-sm text-muted">
        Clears what players did, so challenges used for testing can be deleted
        again. Challenges, hints, skills, areas and every account stay. There is
        no undo.
      </p>

      {groups.isPending ? (
        <Spinner />
      ) : (
        <ul className="mt-4 grid gap-1 sm:grid-cols-2">
          {rows.map((row) => (
            <GroupRow
              key={row.group}
              row={row}
              checked={chosen.has(row.group)}
              onToggle={() => toggle(row.group)}
            />
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <button
          onClick={() => {
            setChosen(new Set(rows.map((r) => r.group)));
            setDone(null);
          }}
          className="underline"
        >
          Select everything
        </button>
        {chosen.size > 0 && (
          <button
            onClick={() => {
              setChosen(new Set());
              setTyped("");
            }}
            className="text-muted underline"
          >
            Clear
          </button>
        )}
      </div>

      {chosen.size > 0 && (
        <div className="mt-4 rounded border border-torch bg-parchment p-3 text-sm">
          <p>
            This deletes <strong>{total.toLocaleString()}</strong>{" "}
            {total === 1 ? "row" : "rows"} across {chosen.size}{" "}
            {chosen.size === 1 ? "group" : "groups"}. It cannot be undone.
          </p>
          <label className="mt-3 block">
            Type <code>RESET</code> to confirm
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              aria-label="Type RESET to confirm"
              className="mt-1 block w-40 rounded border border-stone px-2 py-1"
            />
          </label>
          <button
            onClick={() => run.mutate()}
            disabled={!armed || run.isPending}
            className="mt-3 rounded bg-torch px-4 py-2 text-parchment disabled:opacity-40"
          >
            {run.isPending ? "Clearing…" : "Reset play data"}
          </button>
        </div>
      )}

      <ErrorMessage error={run.error ?? groups.error} />

      {done !== null && (
        <p role="status" className="mt-3 text-sm">
          Cleared <strong>{done.toLocaleString()}</strong>{" "}
          {done === 1 ? "row" : "rows"}.
        </p>
      )}
    </section>
  );
}

/** Greyed rather than hidden when unticked, so the size of what is *not* being
 *  cleared stays visible next to the size of what is. */
function GroupRow({
  row,
  checked,
  onToggle,
}: {
  row: PlayDataGroup;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <label
        className={`flex items-center gap-2 rounded px-2 py-1 ${
          checked ? "bg-white/70" : "text-muted"
        }`}
      >
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span className="flex-1">{row.label}</span>
        <span className="tabular-nums text-xs">{row.rows.toLocaleString()}</span>
      </label>
    </li>
  );
}
