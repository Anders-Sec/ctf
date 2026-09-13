import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  createAchievement,
  deleteAchievement,
  listAchievements,
  listTriggerCodes,
  updateAchievement,
  type AdminAchievement,
} from "../api/adminAchievements";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Managing the achievement roster (spec 030).
 *
 * An achievement is half data and half code. The name, the criteria and the
 * System AI's line are editable text; the code names a trigger that lives in
 * the backend and no amount of UI can conjure one. So this page shows that seam
 * rather than hiding it — a row with no trigger is inert, and finding that out
 * here beats finding it out after the event when nobody earned it.
 */
type Filter = "all" | "needs_copy" | "inert";

export default function AdminAchievementsPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const roster = useQuery({ queryKey: ["admin-achievements"], queryFn: listAchievements });
  const triggers = useQuery({
    queryKey: ["admin-achievement-triggers"],
    queryFn: listTriggerCodes,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-achievements"] });
    queryClient.invalidateQueries({ queryKey: ["admin-achievement-triggers"] });
  };

  const create = useMutation({ mutationFn: createAchievement, onSuccess: refresh });
  const remove = useMutation({ mutationFn: deleteAchievement, onSuccess: refresh });

  const items = useMemo(() => roster.data ?? [], [roster.data]);
  const needingCopy = items.filter((row) => row.needs_copy).length;
  const inert = items.filter((row) => !row.has_trigger).length;

  const shown = items.filter((row) => {
    if (filter === "needs_copy" && !row.needs_copy) return false;
    if (filter === "inert" && row.has_trigger) return false;
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return (
      row.name.toLowerCase().includes(term) ||
      row.code.toLowerCase().includes(term) ||
      row.earned_by.toLowerCase().includes(term)
    );
  });

  if (roster.isPending) return <Spinner label="Reading the roster…" />;
  if (roster.isError) return <ErrorMessage error={roster.error} />;

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Achievements</h1>
        <p className="mt-1 text-sm text-muted">
          {items.length} in the roster. The code names a trigger in the backend —
          a row without one never fires. Descriptions are yours to write; the
          seeded text is a placeholder.
        </p>
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {(
          [
            ["all", `All (${items.length})`],
            ["needs_copy", `Needs copy (${needingCopy})`],
            ["inert", `No trigger (${inert})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded border px-3 py-1.5 text-sm ${
              filter === key
                ? "border-ink bg-ink text-parchment"
                : "border-stone hover:bg-white/60"
            }`}
          >
            {label}
          </button>
        ))}
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search"
          aria-label="Search achievements"
          className="ml-auto rounded border border-stone px-2 py-1.5 text-sm"
        />
      </div>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          Read-only — only admins can change the roster.
        </p>
      )}

      <ErrorMessage error={create.error ?? remove.error} />

      {canWrite && (
        <CreateRow
          unused={triggers.data?.unused ?? []}
          pending={create.isPending}
          onCreate={(input) => create.mutate(input)}
        />
      )}

      <ul className="mt-4 space-y-2">
        {shown.map((row) => (
          <Row
            key={row.id}
            row={row}
            canWrite={canWrite}
            onDelete={() => remove.mutate(row.id)}
            onSaved={refresh}
          />
        ))}
      </ul>

      {shown.length === 0 && (
        <p className="mt-6 text-sm text-muted">Nothing matches that.</p>
      )}
    </main>
  );
}

function CreateRow({
  unused,
  pending,
  onCreate,
}: {
  unused: string[];
  pending: boolean;
  onCreate: (input: { code: string; name: string; earned_by: string }) => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [earnedBy, setEarnedBy] = useState("");

  return (
    <form
      className="mt-4 rounded border border-stone bg-white/40 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onCreate({ code: code.trim(), name: name.trim(), earned_by: earnedBy.trim() });
        setCode("");
        setName("");
        setEarnedBy("");
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-muted">Code</span>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            list="unused-triggers"
            placeholder="lower_snake_case"
            aria-label="New achievement code"
            className="rounded border border-stone px-2 py-1.5 text-sm"
          />
          {/* The useful new achievement is nearly always one whose trigger
              already exists, so those are offered first. */}
          <datalist id="unused-triggers">
            {unused.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-label="New achievement name"
            className="rounded border border-stone px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex-1 text-sm">
          <span className="mb-1 block text-muted">Earned by</span>
          <input
            value={earnedBy}
            onChange={(event) => setEarnedBy(event.target.value)}
            aria-label="New achievement criteria"
            className="w-full rounded border border-stone px-2 py-1.5 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={pending || !code.trim() || !name.trim()}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          Add achievement
        </button>
      </div>
      {unused.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          {unused.length} registered {unused.length === 1 ? "trigger has" : "triggers have"}{" "}
          no achievement yet: {unused.join(", ")}
        </p>
      )}
    </form>
  );
}

function Row({
  row,
  canWrite,
  onDelete,
  onSaved,
}: {
  row: AdminAchievement;
  canWrite: boolean;
  onDelete: () => void;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(row.name);
  const [earnedBy, setEarnedBy] = useState(row.earned_by);
  const [description, setDescription] = useState(row.description);

  const save = useMutation({
    mutationFn: () =>
      updateAchievement(row.id, {
        name: name.trim(),
        earned_by: earnedBy,
        description,
      }),
    onSuccess: () => {
      onSaved();
      setOpen(false);
    },
  });

  return (
    <li className="rounded border border-stone bg-white/50 px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {row.name}
            {!row.has_trigger && (
              <span
                title="No trigger is registered for this code, so it will never fire."
                className="ml-2 rounded-full border border-torch px-2 py-0.5 text-xs font-medium text-torch"
              >
                no trigger
              </span>
            )}
            {row.needs_copy && (
              <span className="ml-2 rounded-full border border-stone px-2 py-0.5 text-xs font-medium text-muted">
                needs copy
              </span>
            )}
            {row.secret && (
              <span className="ml-2 rounded-full border border-stone px-2 py-0.5 text-xs font-medium text-muted">
                secret
              </span>
            )}
          </p>
          <p className="mt-0.5 text-sm text-muted">{row.earned_by}</p>
          <p className="mt-0.5 font-mono text-xs text-muted">{row.code}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-sm">
          <span className="text-muted tabular-nums">
            {row.held_by} {row.held_by === 1 ? "holder" : "holders"}
          </span>
          {canWrite && (
            <>
              <button onClick={() => setOpen((was) => !was)} className="hover:underline">
                {open ? "Cancel" : "Edit"}
              </button>
              <button
                onClick={onDelete}
                disabled={row.held_by > 0}
                title={
                  row.held_by > 0
                    ? "Players hold this. Mark it secret to hide it instead."
                    : undefined
                }
                className="hover:underline disabled:opacity-40 disabled:no-underline"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {open && (
        <form
          className="mt-3 space-y-2 border-t border-stone pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-label={`Name for ${row.code}`}
              className="w-full rounded border border-stone px-2 py-1.5"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Earned by</span>
            <input
              value={earnedBy}
              onChange={(event) => setEarnedBy(event.target.value)}
              aria-label={`Criteria for ${row.code}`}
              className="w-full rounded border border-stone px-2 py-1.5"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">
              Description — the System AI&apos;s line, shown once earned
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
              aria-label={`Description for ${row.code}`}
              className="w-full rounded border border-stone px-2 py-1.5"
            />
          </label>

          <ErrorMessage error={save.error} />

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {/* The code is deliberately not editable: it joins to a trigger and
                to every award already granted. */}
            <span className="text-xs text-muted">
              The code cannot be changed — it links this to its trigger and to
              every award already earned.
            </span>
          </div>
        </form>
      )}
    </li>
  );
}
