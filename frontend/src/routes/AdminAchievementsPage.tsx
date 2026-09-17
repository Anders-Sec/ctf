import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  bulkAchievements,
  createAchievement,
  deleteAchievement,
  listAchievements,
  listTriggerCodes,
  updateAchievement,
  type AdminAchievement,
  type LootBoxType,
  type LootRarity,
} from "../api/adminAchievements";
import type { BulkResult } from "../api/adminSkills";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import {
  ContentBulkBar,
  ContentDrawer,
  ContentFilterBar,
  ContentGroupList,
  ContentPage,
  Field,
  RowFlag,
  SelectBox,
  inputClass,
  type ContentGroup,
} from "../components/content/ContentPage";
import { useSelection } from "../components/content/useSelection";
import { GRANTABLE_THEMES } from "../theme/themes";

/**
 * The achievement roster (spec 030) on the shared Content shape (spec 058).
 *
 * An achievement is half data and half code. The name, the criteria and the
 * System AI's line are editable text; the code names a trigger that lives in the
 * backend and no amount of UI can conjure one. So this page shows that seam
 * rather than hiding it — a row with no trigger is inert, and finding that out
 * here beats finding it out after the event when nobody earned it.
 *
 * What 058 adds is the **reward**. `loot_box_type`, `loot_rarity` and
 * `no_loot_line` were on the model since spec 038 and editable from nowhere, so
 * what an achievement paid out was whatever the seed said, permanently. The
 * theme grant (§5) hangs off the same section.
 *
 * Grouped by loot box, which is the axis an admin works along when balancing
 * rewards — and it puts the ones that pay nothing together, where
 * `no_loot_line` is the thing that matters.
 */
const LOOT_BOXES: LootBoxType[] = [
  "adventurer",
  "boss",
  "brute_force",
  "cartographer",
  "interrogator",
  "party",
  "pathfinder",
  "purist",
  "saboteur",
  "specialist",
];

const RARITIES: LootRarity[] = [
  "bronze",
  "silver",
  "gold",
  "platinum",
  "legendary",
  "celestial",
];

const RARITY_TEXT: Record<LootRarity, string> = {
  bronze: "text-loot-bronze",
  silver: "text-loot-silver",
  gold: "text-loot-gold",
  platinum: "text-loot-platinum",
  legendary: "text-loot-legendary",
  celestial: "text-loot-celestial",
};

const NO_LOOT = "__none__";

const PROBLEMS = {
  needs_copy: (row: AdminAchievement) => row.needs_copy,
  inert: (row: AdminAchievement) => !row.has_trigger,
  /** Pays nothing and says nothing about it. */
  silent: (row: AdminAchievement) =>
    !row.loot_box_type && !row.unlocks_theme && !row.no_loot_line?.trim(),
} satisfies Record<string, (row: AdminAchievement) => boolean>;

type ProblemId = keyof typeof PROBLEMS | "";

function boxLabel(box: LootBoxType | null): string {
  return box ? box.replace(/_/g, " ") : "(no loot)";
}

export default function AdminAchievementsPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const roster = useQuery({ queryKey: ["admin-achievements"], queryFn: listAchievements });
  const triggers = useQuery({
    queryKey: ["admin-achievement-triggers"],
    queryFn: listTriggerCodes,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-achievements"] });
    queryClient.invalidateQueries({ queryKey: ["admin-achievement-triggers"] });
  };

  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<ProblemId>("");
  const [editing, setEditing] = useState<AdminAchievement | "new" | null>(null);
  const [result, setResult] = useState<BulkResult | undefined>(undefined);
  const selection = useSelection();

  const remove = useMutation({
    mutationFn: (id: string) => deleteAchievement(id),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const bulk = useMutation({
    mutationFn: (input: { action: string; value: unknown }) =>
      bulkAchievements([...selection.selected], input.action, input.value),
    onSuccess: (outcome) => {
      setResult(outcome);
      selection.clear();
      refresh();
    },
  });

  const rows = roster.data ?? [];

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (filters.box === NO_LOOT && row.loot_box_type) return false;
      if (filters.box && filters.box !== NO_LOOT && row.loot_box_type !== filters.box) {
        return false;
      }
      if (filters.rarity && row.loot_rarity !== filters.rarity) return false;
      if (filters.secret === "yes" && !row.secret) return false;
      if (filters.secret === "no" && row.secret) return false;
      if (problem && !PROBLEMS[problem](row)) return false;
      if (!term) return true;
      return (
        row.name.toLowerCase().includes(term) ||
        row.code.toLowerCase().includes(term) ||
        row.earned_by.toLowerCase().includes(term)
      );
    });
  }, [rows, search, filters, problem]);

  const groups: ContentGroup[] = useMemo(() => {
    // `(no loot)` last, for the same reason Skills puts `(no zone)` last.
    const keys: (LootBoxType | null)[] = [...LOOT_BOXES, null];
    return keys.map((box) => {
      const members = shown.filter((row) => (row.loot_box_type ?? null) === box);
      const needCopy = members.filter((row) => row.needs_copy).length;
      const inert = members.filter((row) => !row.has_trigger).length;
      return {
        id: box ?? NO_LOOT,
        heading: boxLabel(box),
        count: members.length,
        summary: [
          `${members.length} ${members.length === 1 ? "achievement" : "achievements"}`,
          needCopy > 0 ? `${needCopy} need copy` : null,
          inert > 0 ? `${inert} inert` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        accent: "text-nav-content",
        rows: (
          <ul>
            {members.map((row) => (
              <AchievementRow
                key={row.id}
                row={row}
                canWrite={canWrite}
                selected={selection.selected.has(row.id)}
                onSelect={(on) => selection.toggle(row.id, on)}
                onOpen={() => setEditing(row)}
              />
            ))}
          </ul>
        ),
      };
    });
  }, [shown, canWrite, selection]);

  if (roster.isPending) return <Spinner label="Reading the roster…" />;
  if (roster.isError) return <ErrorMessage error={roster.error} />;

  return (
    <ContentPage
      title="Achievements"
      description={
        <>
          The code names a trigger in the backend — a row without one never
          fires. Descriptions are yours to write; the seeded text is a
          placeholder.
        </>
      }
      newLabel="New achievement"
      onNew={() => setEditing("new")}
      canWrite={canWrite}
      readOnlyNote="Read-only — only admins can change the roster."
      filterBar={
        <ContentFilterBar
          searchLabel="Search achievements"
          search={search}
          onSearchChange={setSearch}
          filters={[
            {
              id: "box",
              label: "Loot box",
              options: [
                ...LOOT_BOXES.map((box) => ({ value: box, label: boxLabel(box) })),
                { value: NO_LOOT, label: "(no loot)" },
              ],
            },
            {
              id: "rarity",
              label: "Rarity",
              options: RARITIES.map((rarity) => ({ value: rarity, label: rarity })),
            },
            {
              id: "secret",
              label: "Secret",
              options: [
                { value: "yes", label: "Secret" },
                { value: "no", label: "Visible" },
              ],
            },
          ]}
          values={filters}
          onFilterChange={(id, value) => setFilters((was) => ({ ...was, [id]: value }))}
          problems={[
            {
              id: "needs_copy",
              label: "need copy",
              count: rows.filter(PROBLEMS.needs_copy).length,
            },
            { id: "inert", label: "no trigger", count: rows.filter(PROBLEMS.inert).length },
            {
              id: "silent",
              label: "pay nothing, say nothing",
              count: rows.filter(PROBLEMS.silent).length,
            },
          ]}
          activeProblem={problem}
          onProblemChange={(id) => setProblem(id as ProblemId)}
          shown={shown.length}
          total={rows.length}
        />
      }
      bulkBar={
        <ContentBulkBar count={selection.selected.size} onClear={selection.clear} result={result}>
          <label className="flex items-center gap-1">
            Loot box
            <select
              aria-label="Set loot box for selected"
              defaultValue=""
              onChange={(event) => {
                if (event.target.value) {
                  const value = event.target.value === NO_LOOT ? null : event.target.value;
                  bulk.mutate({ action: "set_loot_box", value });
                  event.target.value = "";
                }
              }}
              className="rounded border border-border-strong bg-surface-raised px-1 py-0.5"
            >
              <option value="">—</option>
              {LOOT_BOXES.map((box) => (
                <option key={box} value={box}>
                  {boxLabel(box)}
                </option>
              ))}
              <option value={NO_LOOT}>(no loot)</option>
            </select>
          </label>
          <label className="flex items-center gap-1">
            Rarity
            <select
              aria-label="Set rarity for selected"
              defaultValue=""
              onChange={(event) => {
                if (event.target.value) {
                  bulk.mutate({ action: "set_rarity", value: event.target.value });
                  event.target.value = "";
                }
              }}
              className="rounded border border-border-strong bg-surface-raised px-1 py-0.5"
            >
              <option value="">—</option>
              {RARITIES.map((rarity) => (
                <option key={rarity} value={rarity}>
                  {rarity}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => bulk.mutate({ action: "set_secret", value: true })}
            className="underline"
          >
            Mark secret
          </button>
          <button
            type="button"
            onClick={() => bulk.mutate({ action: "set_secret", value: false })}
            className="underline"
          >
            Unmark
          </button>
          <button
            type="button"
            onClick={() => bulk.mutate({ action: "delete", value: null })}
            className="text-danger underline"
          >
            Delete
          </button>
        </ContentBulkBar>
      }
      drawer={
        editing && (
          <AchievementDrawer
            row={editing === "new" ? null : editing}
            unused={triggers.data?.unused ?? []}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              refresh();
            }}
            onDelete={editing !== "new" ? () => remove.mutate(editing.id) : undefined}
          />
        )
      }
    >
      <ErrorMessage error={bulk.error ?? remove.error} />
      <ContentGroupList
        groups={groups}
        storageKey="admin.achievements"
        empty="Nothing matches that."
      />
    </ContentPage>
  );
}

function AchievementRow({
  row,
  canWrite,
  selected,
  onSelect,
  onOpen,
}: {
  row: AdminAchievement;
  canWrite: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <li className="flex items-center gap-2 border-b border-border px-1 py-1 text-sm">
      {canWrite && <SelectBox checked={selected} onChange={onSelect} label={row.name} />}
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 truncate text-left">
        {row.name}
        <span className="ml-2 font-mono text-xs text-content-faint">{row.code}</span>
      </button>
      {!row.has_trigger && (
        <RowFlag tone="warning">no trigger</RowFlag>
      )}
      {row.needs_copy && <RowFlag tone="muted">needs copy</RowFlag>}
      {row.secret && <RowFlag tone="muted">secret</RowFlag>}
      <span className="w-24 shrink-0 truncate text-right text-xs">
        {row.loot_rarity ? (
          <span className={RARITY_TEXT[row.loot_rarity]}>{row.loot_rarity}</span>
        ) : (
          <span className="text-content-faint">—</span>
        )}
      </span>
      {row.unlocks_theme && <RowFlag tone="muted">theme</RowFlag>}
      <span className="w-20 shrink-0 text-right text-xs text-content-muted tabular-nums">
        {row.held_by} {row.held_by === 1 ? "holder" : "holders"}
      </span>
    </li>
  );
}

function AchievementDrawer({
  row,
  unused,
  onClose,
  onSaved,
  onDelete,
}: {
  row: AdminAchievement | null;
  unused: string[];
  onClose: () => void;
  onSaved: () => void;
  onDelete?: () => void;
}) {
  const [code, setCode] = useState(row?.code ?? "");
  const [name, setName] = useState(row?.name ?? "");
  const [earnedBy, setEarnedBy] = useState(row?.earned_by ?? "");
  const [description, setDescription] = useState(row?.description ?? "");
  const [order, setOrder] = useState(String(row?.display_order ?? 0));
  const [secret, setSecret] = useState(row?.secret ?? false);
  const [box, setBox] = useState<string>(row?.loot_box_type ?? "");
  const [rarity, setRarity] = useState<string>(row?.loot_rarity ?? "");
  const [noLootLine, setNoLootLine] = useState(row?.no_loot_line ?? "");
  const [theme, setTheme] = useState(row?.unlocks_theme ?? "");

  const dirty =
    code !== (row?.code ?? "") ||
    name !== (row?.name ?? "") ||
    earnedBy !== (row?.earned_by ?? "") ||
    description !== (row?.description ?? "") ||
    order !== String(row?.display_order ?? 0) ||
    secret !== (row?.secret ?? false) ||
    box !== (row?.loot_box_type ?? "") ||
    rarity !== (row?.loot_rarity ?? "") ||
    noLootLine !== (row?.no_loot_line ?? "") ||
    theme !== (row?.unlocks_theme ?? "");

  const save = useMutation({
    mutationFn: () => {
      const shared = {
        name: name.trim(),
        earned_by: earnedBy,
        description,
        display_order: Number(order) || 0,
        secret,
        no_loot_line: noLootLine.trim() || null,
      };
      if (!row) {
        return createAchievement({
          ...shared,
          code: code.trim(),
          loot_box_type: (box || null) as LootBoxType | null,
          loot_rarity: (rarity || null) as LootRarity | null,
          unlocks_theme: theme || null,
        });
      }
      // Null in a PATCH means "not sent", so clearing a reward needs its own
      // flag rather than an absent field the server cannot tell apart.
      return updateAchievement(row.id, {
        ...shared,
        ...(box
          ? {
              loot_box_type: box as LootBoxType,
              loot_rarity: (rarity || null) as LootRarity | null,
            }
          : { clear_loot: true }),
        ...(theme ? { unlocks_theme: theme } : { clear_theme: true }),
      });
    },
    onSuccess: onSaved,
  });

  const pays = Boolean(box) || Boolean(theme);

  return (
    <ContentDrawer
      title={row ? row.name : "New achievement"}
      subtitle={
        row
          ? `${row.code} · ${row.held_by} ${row.held_by === 1 ? "holder" : "holders"}`
          : undefined
      }
      dirty={dirty}
      onClose={onClose}
      onDelete={onDelete}
      deleteDisabled={(row?.held_by ?? 0) > 0}
      deleteTitle={
        (row?.held_by ?? 0) > 0
          ? "Players hold this. Mark it secret to hide it instead — an earned achievement is never taken back."
          : undefined
      }
      footer={
        <>
          <ErrorMessage error={save.error} />
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || !name.trim() || (!row && !code.trim())}
            className="rounded bg-accent-strong px-4 py-1.5 text-sm font-medium text-accent-content disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      {row ? (
        // Never editable: the code joins to a trigger and to every award
        // already granted (spec 030).
        <Field
          label="Code"
          hint="Fixed — it links this to its trigger and to every award already earned."
        >
          <p className="font-mono text-sm">{row.code}</p>
        </Field>
      ) : (
        <Field label="Code" hint="lower_snake_case, and it must match a registered trigger.">
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            list="unused-triggers"
            aria-label="Achievement code"
            className={inputClass}
          />
          {/* The useful new achievement is nearly always one whose trigger
              already exists, so those are offered first. */}
          <datalist id="unused-triggers">
            {unused.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        </Field>
      )}

      <Field label="Name">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Achievement name"
          className={inputClass}
        />
      </Field>
      <Field label="Earned by">
        <input
          value={earnedBy}
          onChange={(event) => setEarnedBy(event.target.value)}
          aria-label="Achievement criteria"
          className={inputClass}
        />
      </Field>
      <Field label="Description" hint="The System AI's line, shown once earned.">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={3}
          aria-label="Achievement description"
          className={inputClass}
        />
      </Field>
      <Field label="Display order">
        <input
          type="number"
          value={order}
          onChange={(event) => setOrder(event.target.value)}
          aria-label="Achievement display order"
          className={inputClass}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={secret}
          onChange={(event) => setSecret(event.target.checked)}
        />
        Secret — hidden from the list until earned
      </label>

      <fieldset className="border-t border-border pt-3">
        <legend className="text-sm font-medium text-content-muted">Reward</legend>
        <p className="mb-2 text-xs text-content-faint">
          A loot box and a theme are independent; either may be empty. One that
          gives neither still needs a line saying so.
        </p>
        <div className="flex flex-col gap-3">
          <Field label="Loot box">
            <select
              value={box}
              onChange={(event) => {
                setBox(event.target.value);
                // A box and a rarity travel together; a rarity describing no
                // box is the state that made the seeded data hard to read.
                if (!event.target.value) setRarity("");
              }}
              aria-label="Loot box type"
              className={inputClass}
            >
              <option value="">(none)</option>
              {LOOT_BOXES.map((option) => (
                <option key={option} value={option}>
                  {boxLabel(option)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Loot rarity">
            <select
              value={rarity}
              onChange={(event) => setRarity(event.target.value)}
              disabled={!box}
              aria-label="Loot rarity"
              className={`${inputClass} disabled:opacity-50`}
            >
              <option value="">(none)</option>
              {RARITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Unlocks theme"
            hint="Secret themes only. Earning this hands the theme over; it is not granted retroactively."
          >
            <select
              value={theme}
              onChange={(event) => setTheme(event.target.value)}
              aria-label="Unlocks theme"
              className={inputClass}
            >
              <option value="">(none)</option>
              {GRANTABLE_THEMES.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="No-loot line"
            hint={
              pays
                ? "Only shown when there is nothing to hand over."
                : "Required — this achievement pays nothing, so this is all the player sees."
            }
          >
            <input
              value={noLootLine}
              onChange={(event) => setNoLootLine(event.target.value)}
              aria-label="No-loot line"
              className={inputClass}
            />
          </Field>
          {!pays && !noLootLine.trim() && (
            <p className="text-xs text-warning">
              This pays nothing and says nothing about it.
            </p>
          )}
        </div>
      </fieldset>
    </ContentDrawer>
  );
}
