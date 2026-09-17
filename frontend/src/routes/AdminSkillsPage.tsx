import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  bulkSkills,
  createSkill,
  deleteSkill,
  listCategories,
  listSkills,
  setCategoryAbility,
  updateSkill,
  type Ability,
  type BulkResult,
  type Skill,
  type SkillKind,
} from "../api/adminSkills";
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

/**
 * Skills, and the category→ability map (spec 018), on the shared Content shape
 * (spec 058).
 *
 * Skills attach to individual *challenges* (in the challenge editor), not to
 * categories — a challenge feeds every skill on it in full. Categories instead
 * feed one of the six abilities, which is what partitions a player's XP into a
 * stat block, so every category must have one.
 *
 * What 058 adds here is the whole of the model: `kind` and `category_id` and
 * `description` were all in `UpdateSkillRequest` and reachable from no UI, which
 * meant creating a funny skill was impossible from the page that manages them.
 */
const ABILITIES: [Ability, string][] = [
  ["str", "Strength"],
  ["dex", "Dexterity"],
  ["con", "Constitution"],
  ["int", "Intelligence"],
  ["wis", "Wisdom"],
  ["cha", "Charisma"],
];

const KINDS: SkillKind[] = ["useful", "funny"];

/** A skill no challenge feeds is XP that lands nowhere on anybody's sheet. */
const PROBLEMS = {
  orphan: (skill: Skill) => skill.challenge_count === 0,
  no_zone: (skill: Skill) => skill.category_id === null,
  no_copy: (skill: Skill) => !skill.description?.trim(),
} satisfies Record<string, (skill: Skill) => boolean>;

type ProblemId = keyof typeof PROBLEMS | "";

const NO_ZONE = "__none__";

export default function AdminSkillsPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const skills = useQuery({ queryKey: ["admin", "skills"], queryFn: listSkills });
  const categories = useQuery({
    queryKey: ["admin", "skill-categories"],
    queryFn: listCategories,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["admin", "skills"] });
    queryClient.invalidateQueries({ queryKey: ["admin", "skill-categories"] });
  };

  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<ProblemId>("");
  const [editing, setEditing] = useState<Skill | "new" | null>(null);
  const [result, setResult] = useState<BulkResult | undefined>(undefined);
  const selection = useSelection();

  const remove = useMutation({
    mutationFn: (skillId: string) => deleteSkill(skillId),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
  });
  const bulk = useMutation({
    mutationFn: (input: { action: string; value: unknown }) =>
      bulkSkills([...selection.selected], input.action, input.value),
    onSuccess: (outcome) => {
      setResult(outcome);
      selection.clear();
      invalidate();
    },
  });
  const mapAbility = useMutation({
    mutationFn: (input: { categoryId: string; ability: Ability }) =>
      setCategoryAbility(input.categoryId, input.ability),
    onSuccess: invalidate,
  });

  const rows = skills.data ?? [];
  const zones = categories.data ?? [];
  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((skill) => {
      if (filters.kind && skill.kind !== filters.kind) return false;
      if (filters.zone === NO_ZONE && skill.category_id !== null) return false;
      if (filters.zone && filters.zone !== NO_ZONE && skill.category_id !== filters.zone) {
        return false;
      }
      if (problem && !PROBLEMS[problem](skill)) return false;
      if (!term) return true;
      return (
        skill.name.toLowerCase().includes(term) ||
        (skill.description ?? "").toLowerCase().includes(term)
      );
    });
  }, [rows, search, filters, problem]);

  const groups: ContentGroup[] = useMemo(() => {
    // `(no zone)` last: a skill without one is not an error — the model's SET
    // NULL is deliberate — but it is worth seeing them together.
    const ordered = [...zones, { id: NO_ZONE, name: "(no zone)", display_order: 9999 }];
    return ordered.map((zone) => {
      const members = shown.filter(
        (skill) => (skill.category_id ?? NO_ZONE) === zone.id,
      );
      const funny = members.filter((skill) => skill.kind === "funny").length;
      const challenges = members.reduce((sum, skill) => sum + skill.challenge_count, 0);
      return {
        id: zone.id,
        heading: zone.name,
        count: members.length,
        summary: [
          `${members.length} ${members.length === 1 ? "skill" : "skills"}`,
          funny > 0 ? `${funny} funny` : null,
          `${challenges} ${challenges === 1 ? "challenge" : "challenges"}`,
        ]
          .filter(Boolean)
          .join(" · "),
        accent: "text-nav-content",
        rows: (
          <ul>
            {members.map((skill) => (
              <SkillRow
                key={skill.id}
                skill={skill}
                canWrite={canWrite}
                selected={selection.selected.has(skill.id)}
                onSelect={(on) => selection.toggle(skill.id, on)}
                onOpen={() => setEditing(skill)}
              />
            ))}
          </ul>
        ),
      };
    });
  }, [shown, zones, canWrite, selection]);

  if (skills.isPending || categories.isPending) return <Spinner />;
  if (skills.isError) return <ErrorMessage error={skills.error} />;
  if (categories.isError) return <ErrorMessage error={categories.error} />;

  return (
    <ContentPage
      title="Skills"
      description={
        <>
          Skills attach to individual challenges, and solving one feeds every
          skill on it. Categories feed an <strong>ability</strong> instead — that
          mapping is at the bottom, and every category needs one.
        </>
      }
      newLabel="New skill"
      onNew={() => setEditing("new")}
      canWrite={canWrite}
      readOnlyNote="Read-only — only admins can change skills."
      filterBar={
        <ContentFilterBar
          searchLabel="Search skills"
          search={search}
          onSearchChange={setSearch}
          filters={[
            {
              id: "kind",
              label: "Kind",
              options: KINDS.map((kind) => ({ value: kind, label: kind })),
            },
            {
              id: "zone",
              label: "Zone",
              options: [
                ...zones.map((zone) => ({ value: zone.id, label: zone.name })),
                { value: NO_ZONE, label: "(no zone)" },
              ],
            },
          ]}
          values={filters}
          onFilterChange={(id, value) =>
            setFilters((was) => ({ ...was, [id]: value }))
          }
          problems={[
            {
              id: "orphan",
              label: "attached to nothing",
              count: rows.filter(PROBLEMS.orphan).length,
            },
            { id: "no_zone", label: "no zone", count: rows.filter(PROBLEMS.no_zone).length },
            {
              id: "no_copy",
              label: "no description",
              count: rows.filter(PROBLEMS.no_copy).length,
            },
          ]}
          activeProblem={problem}
          onProblemChange={(id) => setProblem(id as ProblemId)}
          shown={shown.length}
          total={rows.length}
        />
      }
      bulkBar={
        <ContentBulkBar
          count={selection.selected.size}
          onClear={selection.clear}
          result={result}
        >
          <label className="flex items-center gap-1">
            Kind
            <select
              aria-label="Set kind for selected"
              defaultValue=""
              onChange={(event) => {
                if (event.target.value) {
                  bulk.mutate({ action: "set_kind", value: event.target.value });
                  event.target.value = "";
                }
              }}
              className="rounded border border-border-strong bg-surface-raised px-1 py-0.5"
            >
              <option value="">—</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            Zone
            <select
              aria-label="Set zone for selected"
              defaultValue=""
              onChange={(event) => {
                if (event.target.value) {
                  const value = event.target.value === NO_ZONE ? null : event.target.value;
                  bulk.mutate({ action: "set_category", value });
                  event.target.value = "";
                }
              }}
              className="rounded border border-border-strong bg-surface-raised px-1 py-0.5"
            >
              <option value="">—</option>
              {zones.map((zone) => (
                <option key={zone.id} value={zone.id}>
                  {zone.name}
                </option>
              ))}
              <option value={NO_ZONE}>(no zone)</option>
            </select>
          </label>
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
          <SkillDrawer
            skill={editing === "new" ? null : editing}
            zones={zones}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              invalidate();
            }}
            onDelete={
              editing !== "new" ? () => remove.mutate(editing.id) : undefined
            }
          />
        )
      }
    >
      <ErrorMessage error={bulk.error ?? remove.error} />
      <ContentGroupList
        groups={groups}
        storageKey="admin.skills"
        empty="Nothing matches that."
      />

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-lg font-semibold">Category → ability</h2>
        <p className="mt-1 text-sm text-content-muted">
          Which of the six abilities each zone&apos;s XP feeds. Every category
          needs one, or its XP drops out of the stat block.
        </p>
        <ul className="mt-3 max-w-xl space-y-1">
          {zones.map((category) => (
            <li
              key={category.id}
              className="flex items-center justify-between gap-3 rounded border border-border bg-surface-raised px-3 py-1.5 text-sm"
            >
              <span>{category.name}</span>
              <select
                aria-label={`Ability for ${category.name}`}
                value={category.ability}
                disabled={!canWrite || mapAbility.isPending}
                onChange={(event) =>
                  mapAbility.mutate({
                    categoryId: category.id,
                    ability: event.target.value as Ability,
                  })
                }
                className="rounded border border-border-strong bg-surface-raised px-2 py-1"
              >
                {ABILITIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </li>
          ))}
        </ul>
        <ErrorMessage error={mapAbility.error} />
      </section>
    </ContentPage>
  );
}

/** Short on purpose: what a skill is found and scanned by, nothing else. */
function SkillRow({
  skill,
  canWrite,
  selected,
  onSelect,
  onOpen,
}: {
  skill: Skill;
  canWrite: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <li className="flex items-center gap-2 border-b border-border px-1 py-1 text-sm">
      {canWrite && (
        <SelectBox checked={selected} onChange={onSelect} label={skill.name} />
      )}
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 truncate text-left">
        {skill.name}
      </button>
      {skill.kind === "funny" && <RowFlag tone="muted">funny</RowFlag>}
      {/* Marked in the list, not only in the drawer (§6). */}
      {skill.challenge_count === 0 && <RowFlag tone="warning">unattached</RowFlag>}
      {!skill.description?.trim() && <RowFlag tone="muted">no copy</RowFlag>}
      <span className="w-20 shrink-0 text-right text-xs text-content-muted tabular-nums">
        {skill.challenge_count} ch.
      </span>
    </li>
  );
}

function SkillDrawer({
  skill,
  zones,
  onClose,
  onSaved,
  onDelete,
}: {
  skill: Skill | null;
  zones: { id: string; name: string }[];
  onClose: () => void;
  onSaved: () => void;
  onDelete?: () => void;
}) {
  const [name, setName] = useState(skill?.name ?? "");
  const [kind, setKind] = useState<SkillKind>(skill?.kind ?? "useful");
  const [zone, setZone] = useState(skill?.category_id ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [order, setOrder] = useState(String(skill?.display_order ?? 0));

  const dirty =
    name !== (skill?.name ?? "") ||
    kind !== (skill?.kind ?? "useful") ||
    zone !== (skill?.category_id ?? "") ||
    description !== (skill?.description ?? "") ||
    order !== String(skill?.display_order ?? 0);

  const save = useMutation({
    mutationFn: () => {
      const input = {
        name: name.trim(),
        kind,
        category_id: zone || null,
        description: description.trim() || null,
        display_order: Number(order) || 0,
      };
      return skill ? updateSkill(skill.id, input) : createSkill(input);
    },
    onSuccess: onSaved,
  });

  return (
    <ContentDrawer
      title={skill ? skill.name : "New skill"}
      subtitle={
        skill
          ? `${skill.challenge_count} ${skill.challenge_count === 1 ? "challenge" : "challenges"} feed this`
          : undefined
      }
      dirty={dirty}
      onClose={onClose}
      onDelete={onDelete}
      footer={
        <>
          <ErrorMessage error={save.error} />
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || !name.trim()}
            className="rounded bg-accent-strong px-4 py-1.5 text-sm font-medium text-accent-content disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <Field label="Name">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Skill name"
          className={inputClass}
        />
      </Field>
      <Field label="Kind" hint="Funny skills are the joke; players can filter them out.">
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as SkillKind)}
          aria-label="Skill kind"
          className={inputClass}
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Zone" hint="Sorts the challenge editor's picker; it restricts nothing.">
        <select
          value={zone}
          onChange={(event) => setZone(event.target.value)}
          aria-label="Skill zone"
          className={inputClass}
        >
          <option value="">(no zone)</option>
          {zones.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Description">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={3}
          aria-label="Skill description"
          className={inputClass}
        />
      </Field>
      <Field label="Display order">
        <input
          type="number"
          value={order}
          onChange={(event) => setOrder(event.target.value)}
          aria-label="Skill display order"
          className={inputClass}
        />
      </Field>
    </ContentDrawer>
  );
}
