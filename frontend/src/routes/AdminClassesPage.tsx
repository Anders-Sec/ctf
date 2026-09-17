import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  bulkClasses,
  createClass,
  deleteClass,
  listClasses,
  setClassPreferences,
  setClassRequirements,
  updateClass,
  type CharacterClass,
  type ClassPreference,
  type ClassRequirement,
  type Rarity,
} from "../api/adminClasses";
import { listSkills, type Ability, type BulkResult, type Skill } from "../api/adminSkills";
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
 * Character classes (spec 016) on the shared Content shape (spec 058).
 *
 * A class is roster and identity: it never touches scoring. What it *does* drive
 * is spec 024's recommender — preferences say what a class looks for, and
 * requirements are the skill levels that gate it. Both were on the model and
 * editable from nowhere until 058, which meant the whole recommendation model
 * was seed-only.
 *
 * Grouped by rarity, which is the axis the roster is authored along: it splits
 * 48 classes five ways and is already a theme-invariant colour ladder that
 * carries its own name as text.
 */
const RARITIES: Rarity[] = ["common", "uncommon", "rare", "legendary", "mythic"];

const RARITY_TEXT: Record<Rarity, string> = {
  common: "text-rarity-common",
  uncommon: "text-rarity-uncommon",
  rare: "text-rarity-rare",
  legendary: "text-rarity-legendary",
  mythic: "text-rarity-mythic",
};

const ABILITIES: Ability[] = ["str", "dex", "con", "int", "wis", "cha"];

const PROBLEMS = {
  no_requirements: (row: CharacterClass) => row.requirement_count === 0,
  no_preferences: (row: CharacterClass) => row.preference_count === 0,
  needs_copy: (row: CharacterClass) => !row.description?.trim(),
} satisfies Record<string, (row: CharacterClass) => boolean>;

type ProblemId = keyof typeof PROBLEMS | "";

export default function AdminClassesPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const classes = useQuery({ queryKey: ["admin", "classes"], queryFn: listClasses });
  const skills = useQuery({ queryKey: ["admin", "skills"], queryFn: listSkills });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "classes"] });

  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<ProblemId>("");
  const [editing, setEditing] = useState<CharacterClass | "new" | null>(null);
  const [result, setResult] = useState<BulkResult | undefined>(undefined);
  const selection = useSelection();

  const remove = useMutation({
    mutationFn: (classId: string) => deleteClass(classId),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
  });
  const bulk = useMutation({
    mutationFn: (input: { action: string; value: unknown }) =>
      bulkClasses([...selection.selected], input.action, input.value),
    onSuccess: (outcome) => {
      setResult(outcome);
      selection.clear();
      invalidate();
    },
  });

  const rows = classes.data ?? [];

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (filters.rarity && row.rarity !== filters.rarity) return false;
      if (filters.requirements === "yes" && row.requirement_count === 0) return false;
      if (filters.requirements === "no" && row.requirement_count > 0) return false;
      if (filters.preferences === "yes" && row.preference_count === 0) return false;
      if (filters.preferences === "no" && row.preference_count > 0) return false;
      if (problem && !PROBLEMS[problem](row)) return false;
      if (!term) return true;
      return (
        row.name.toLowerCase().includes(term) ||
        (row.description ?? "").toLowerCase().includes(term)
      );
    });
  }, [rows, search, filters, problem]);

  const groups: ContentGroup[] = useMemo(
    () =>
      RARITIES.map((rarity) => {
        const members = shown.filter((row) => row.rarity === rarity);
        const ungated = members.filter((row) => row.requirement_count === 0).length;
        return {
          id: rarity,
          heading: rarity,
          count: members.length,
          accent: RARITY_TEXT[rarity],
          summary: [
            `${members.length} ${members.length === 1 ? "class" : "classes"}`,
            ungated > 0 ? `${ungated} with no requirements` : null,
          ]
            .filter(Boolean)
            .join(" · "),
          rows: (
            <ul>
              {members.map((row) => (
                <ClassRow
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
      }),
    [shown, canWrite, selection],
  );

  if (classes.isPending || skills.isPending) return <Spinner />;
  if (classes.isError) return <ErrorMessage error={classes.error} />;
  if (skills.isError) return <ErrorMessage error={skills.error} />;

  return (
    <ContentPage
      title="Classes"
      description={
        <>
          The archetypes players pick from. Preferences are what the recommender
          matches a player against; requirements are the skill levels that gate
          the class. Rarity is colour and nothing else.
        </>
      }
      newLabel="New class"
      onNew={() => setEditing("new")}
      canWrite={canWrite}
      readOnlyNote="Read-only — only admins can change classes."
      filterBar={
        <ContentFilterBar
          searchLabel="Search classes"
          search={search}
          onSearchChange={setSearch}
          filters={[
            {
              id: "rarity",
              label: "Rarity",
              options: RARITIES.map((rarity) => ({ value: rarity, label: rarity })),
            },
            {
              id: "requirements",
              label: "Requirements",
              options: [
                { value: "yes", label: "Has some" },
                { value: "no", label: "None" },
              ],
            },
            {
              id: "preferences",
              label: "Preferences",
              options: [
                { value: "yes", label: "Has some" },
                { value: "no", label: "None" },
              ],
            },
          ]}
          values={filters}
          onFilterChange={(id, value) => setFilters((was) => ({ ...was, [id]: value }))}
          problems={[
            {
              id: "no_requirements",
              label: "ungated",
              count: rows.filter(PROBLEMS.no_requirements).length,
            },
            {
              id: "no_preferences",
              label: "unrecommendable",
              count: rows.filter(PROBLEMS.no_preferences).length,
            },
            {
              id: "needs_copy",
              label: "need copy",
              count: rows.filter(PROBLEMS.needs_copy).length,
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
            onClick={() => bulk.mutate({ action: "delete", value: null })}
            className="text-danger underline"
          >
            Delete
          </button>
        </ContentBulkBar>
      }
      drawer={
        editing && (
          <ClassDrawer
            row={editing === "new" ? null : editing}
            skills={skills.data}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              invalidate();
            }}
            onDelete={editing !== "new" ? () => remove.mutate(editing.id) : undefined}
          />
        )
      }
    >
      <ErrorMessage error={bulk.error ?? remove.error} />
      <ContentGroupList groups={groups} storageKey="admin.classes" empty="Nothing matches that." />
    </ContentPage>
  );
}

function ClassRow({
  row,
  canWrite,
  selected,
  onSelect,
  onOpen,
}: {
  row: CharacterClass;
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
      </button>
      {/* The name as well as the colour, always (§6). */}
      <span className={`shrink-0 text-xs ${RARITY_TEXT[row.rarity]}`}>{row.rarity}</span>
      {row.requirement_count === 0 && <RowFlag tone="warning">ungated</RowFlag>}
      <span className="w-32 shrink-0 text-right text-xs text-content-muted tabular-nums">
        {row.preference_count} pref · {row.requirement_count} req
      </span>
      <span className="w-20 shrink-0 text-right text-xs text-content-muted tabular-nums">
        {row.wearers} {row.wearers === 1 ? "player" : "players"}
      </span>
    </li>
  );
}

function ClassDrawer({
  row,
  skills,
  onClose,
  onSaved,
  onDelete,
}: {
  row: CharacterClass | null;
  skills: Skill[];
  onClose: () => void;
  onSaved: () => void;
  onDelete?: () => void;
}) {
  const [name, setName] = useState(row?.name ?? "");
  const [rarity, setRarity] = useState<Rarity>(row?.rarity ?? "common");
  const [description, setDescription] = useState(row?.description ?? "");
  const [order, setOrder] = useState(String(row?.display_order ?? 0));
  const [preferences, setPreferences] = useState<ClassPreference[]>(row?.preferences ?? []);
  const [requirements, setRequirements] = useState<ClassRequirement[]>(row?.requirements ?? []);

  const fieldsDirty =
    name !== (row?.name ?? "") ||
    rarity !== (row?.rarity ?? "common") ||
    description !== (row?.description ?? "") ||
    order !== String(row?.display_order ?? 0);
  const setsDirty =
    JSON.stringify(preferences) !== JSON.stringify(row?.preferences ?? []) ||
    JSON.stringify(requirements) !== JSON.stringify(row?.requirements ?? []);

  const save = useMutation({
    mutationFn: async () => {
      const input = {
        name: name.trim(),
        rarity,
        description: description.trim() || null,
        display_order: Number(order) || 0,
      };
      // Create first: the preference and requirement endpoints address a class
      // by id, so a new one has to exist before either can be set.
      const saved = row ? await updateClass(row.id, input) : await createClass(input);
      if (setsDirty || !row) {
        await setClassPreferences(saved.id, preferences);
        await setClassRequirements(saved.id, requirements);
      }
      return saved;
    },
    onSuccess: onSaved,
  });

  const skillName = (id: string | null) =>
    skills.find((skill) => skill.id === id)?.name ?? "—";

  return (
    <ContentDrawer
      title={row ? row.name : "New class"}
      subtitle={
        row
          ? `${row.wearers} ${row.wearers === 1 ? "player is" : "players are"} wearing it`
          : undefined
      }
      dirty={fieldsDirty || setsDirty}
      onClose={onClose}
      onDelete={onDelete}
      deleteDisabled={(row?.wearers ?? 0) > 0}
      deleteTitle={
        (row?.wearers ?? 0) > 0
          ? "Players are wearing this. Deleting would silently return them to Classless."
          : undefined
      }
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
          aria-label="Class name"
          className={inputClass}
        />
      </Field>
      <Field label="Rarity" hint="Colour only — the requirements below do the gating.">
        <select
          value={rarity}
          onChange={(event) => setRarity(event.target.value as Rarity)}
          aria-label="Class rarity"
          className={inputClass}
        >
          {RARITIES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Description">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={3}
          aria-label="Class description"
          className={inputClass}
        />
      </Field>
      <Field label="Display order">
        <input
          type="number"
          value={order}
          onChange={(event) => setOrder(event.target.value)}
          aria-label="Class display order"
          className={inputClass}
        />
      </Field>

      <fieldset className="border-t border-border pt-3">
        <legend className="text-sm font-medium text-content-muted">Preferences</legend>
        <p className="mb-2 text-xs text-content-faint">
          What the recommender matches a player against. Each one is an ability{" "}
          <em>or</em> a skill, never both.
        </p>
        {preferences.map((preference, index) => (
          <div key={index} className="mb-1 flex items-center gap-2 text-sm">
            <select
              aria-label={`Preference ${index + 1} kind`}
              value={preference.skill_id ? "skill" : "ability"}
              onChange={(event) =>
                setPreferences((was) =>
                  was.map((item, position) =>
                    position === index
                      ? event.target.value === "skill"
                        ? { ability: null, skill_id: skills[0]?.id ?? null }
                        : { ability: "int", skill_id: null }
                      : item,
                  ),
                )
              }
              className="rounded border border-border-strong bg-surface-raised px-1 py-1"
            >
              <option value="ability">Ability</option>
              <option value="skill">Skill</option>
            </select>
            {preference.skill_id ? (
              <select
                aria-label={`Preference ${index + 1} skill`}
                value={preference.skill_id}
                onChange={(event) =>
                  setPreferences((was) =>
                    was.map((item, position) =>
                      position === index
                        ? { ability: null, skill_id: event.target.value }
                        : item,
                    ),
                  )
                }
                className="min-w-0 flex-1 rounded border border-border-strong bg-surface-raised px-1 py-1"
              >
                {skills.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name}
                  </option>
                ))}
              </select>
            ) : (
              <select
                aria-label={`Preference ${index + 1} ability`}
                value={preference.ability ?? "int"}
                onChange={(event) =>
                  setPreferences((was) =>
                    was.map((item, position) =>
                      position === index
                        ? { ability: event.target.value as Ability, skill_id: null }
                        : item,
                    ),
                  )
                }
                className="min-w-0 flex-1 rounded border border-border-strong bg-surface-raised px-1 py-1"
              >
                {ABILITIES.map((ability) => (
                  <option key={ability} value={ability}>
                    {ability}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              onClick={() =>
                setPreferences((was) => was.filter((_, position) => position !== index))
              }
              aria-label={`Remove preference ${index + 1}`}
              className="text-content-muted"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setPreferences((was) => [...was, { ability: "int", skill_id: null }])}
          className="mt-1 text-sm underline"
        >
          + Add preference
        </button>
      </fieldset>

      <fieldset className="border-t border-border pt-3">
        <legend className="text-sm font-medium text-content-muted">Requirements</legend>
        <p className="mb-2 text-xs text-content-faint">
          The skill levels that gate the class. None means anybody can take it.
        </p>
        {requirements.map((requirement, index) => (
          <div key={index} className="mb-1 flex items-center gap-2 text-sm">
            <select
              aria-label={`Requirement ${index + 1} skill`}
              value={requirement.skill_id}
              onChange={(event) =>
                setRequirements((was) =>
                  was.map((item, position) =>
                    position === index ? { ...item, skill_id: event.target.value } : item,
                  ),
                )
              }
              className="min-w-0 flex-1 rounded border border-border-strong bg-surface-raised px-1 py-1"
            >
              {skills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={1}
              max={20}
              value={requirement.min_level}
              onChange={(event) =>
                setRequirements((was) =>
                  was.map((item, position) =>
                    position === index
                      ? { ...item, min_level: Number(event.target.value) || 1 }
                      : item,
                  ),
                )
              }
              aria-label={`Requirement ${index + 1} level for ${skillName(requirement.skill_id)}`}
              className="w-16 rounded border border-border-strong bg-surface-raised px-1 py-1"
            />
            <button
              type="button"
              onClick={() =>
                setRequirements((was) => was.filter((_, position) => position !== index))
              }
              aria-label={`Remove requirement ${index + 1}`}
              className="text-content-muted"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            setRequirements((was) => [
              ...was,
              { skill_id: skills[0]?.id ?? "", min_level: 1 },
            ])
          }
          disabled={skills.length === 0}
          className="mt-1 text-sm underline disabled:opacity-50"
        >
          + Add requirement
        </button>
      </fieldset>
    </ContentDrawer>
  );
}
