import { BOSS_TIERS, BOSS_TIER_LABEL, type BossTier } from "../api/bosses";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import {
  addAnswer,
  addPrerequisite,
  createChallenge,
  deleteChallenge,
  deleteAnswer,
  getAdminChallenge,
  listAdminCategories,
  listAdminChallenges,
  listZones,
  removePrerequisite,
  setChallengeState,
  testAnswer,
  updateChallenge,
  type AdminChallengeDetail,
  type ChallengeFilters,
  type Problem,
  type UpdateChallengeInput,
  type ZoneSummary,
} from "../api/adminChallenges";
import {
  createHint,
  deleteHint,
  listHints,
  updateHint,
  type AdminHint,
} from "../api/adminHints";
import { listTemplates } from "../api/adminTemplates";
import type { ChallengeState, Difficulty, MatchType } from "../api/challenges";
import { useSession } from "../auth/session";
import {
  getChallengeSkills,
  listSkills,
  setChallengeSkills,
} from "../api/adminSkills";
import BulkToolbar from "../components/BulkToolbar";
import ChallengeCsvPanel from "../components/ChallengeCsvPanel";
import ChallengeTable from "../components/ChallengeTable";
import ErrorMessage from "../components/ErrorMessage";
import SkillPicker from "../components/SkillPicker";
import Spinner from "../components/Spinner";

const MATCH_TYPES: { value: MatchType; label: string; hint: string }[] = [
  {
    value: "exact",
    label: "Exact",
    hint: "The answer, character for character",
  },
  {
    value: "case_insensitive",
    label: "Ignore case",
    hint: "Same, but case does not matter",
  },
  {
    value: "regex",
    label: "Pattern",
    hint: "A regular expression, anchored by default",
  },
  { value: "numeric", label: "Number", hint: "1000, 1,000 and 1e3 all match" },
  {
    value: "set",
    label: "Multi-part",
    hint: "Comma-separated, any order by default",
  },
  {
    value: "any_of",
    label: "Alternatives",
    hint: "One accepted answer per line",
  },
];

const STATES: ChallengeState[] = ["draft", "hidden", "locked", "published"];

/**
 * The challenge manager (spec 041).
 *
 * A table grouped by zone with a drawer over the right-hand side, rather than a
 * flat list whose editor expands inline. The drawer is the load-bearing part:
 * **the list does not move** while you edit, so you keep your place in 242 rows
 * and the row you are working on stays visible — and a selection checkbox is
 * safe to click, which an inline expander shoving rows around would not be.
 */
export default function AdminChallengesPage() {
  const { me } = useSession();
  const [openId, setOpenId] = useState<string | null>(null);
  const [filters, setFilters] = useState<ChallengeFilters>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(readCollapsed);

  const challenges = useQuery({
    queryKey: ["admin", "challenges", filters],
    queryFn: () => listAdminChallenges(filters),
  });
  const zones = useQuery({ queryKey: ["admin", "zones"], queryFn: listZones });

  const canWrite = me?.capabilities.administer ?? false;
  const rows = challenges.data ?? [];

  const toggleZone = (slug: string) => {
    const next = new Set(collapsed);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    setCollapsed(next);
    writeCollapsed(next);
  };

  return (
    <main className="mx-auto max-w-[1600px] p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Challenges</h1>
        <span className="text-muted">
          {rows.length}
          {hasFilters(filters) ? " matching" : " total"}
        </span>
      </header>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          You have read-only access. Only admins can change challenges.
        </p>
      )}

      {canWrite && <CreateChallengeForm />}

      <FilterBar
        filters={filters}
        onChange={setFilters}
        zones={zones.data ?? []}
      />

      {challenges.isPending ? (
        <Spinner />
      ) : (
        <ChallengeTable
          challenges={rows}
          zones={zones.data ?? []}
          canWrite={canWrite}
          selected={selected}
          onSelectedChange={setSelected}
          openId={openId}
          onOpen={setOpenId}
          collapsed={collapsed}
          onToggleZone={toggleZone}
        />
      )}

      {canWrite && (
        <BulkToolbar
          selected={[...selected]}
          onClear={() => setSelected(new Set())}
          matchingCount={rows.length}
          onSelectAllMatching={() => setSelected(new Set(rows.map((r) => r.id)))}
        />
      )}

      {openId && (
        <ChallengeDrawer
          challengeId={openId}
          canWrite={canWrite}
          onClose={() => setOpenId(null)}
          onDeleted={() => {
            setOpenId(null);
            void challenges.refetch();
            void zones.refetch();
          }}
        />
      )}

      <ChallengeCsvPanel />
    </main>
  );
}

const COLLAPSED_KEY = "ctf.admin.collapsedZones";

/** Per-viewer convenience only, so a throwing or empty read is not a problem. */
function readCollapsed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function writeCollapsed(value: Set<string>) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...value]));
  } catch {
    // A private window, or blocked site data. The page works without it.
  }
}

function hasFilters(filters: ChallengeFilters) {
  return Object.values(filters).some((v) => v !== undefined && v !== "");
}

/**
 * Search, the ordinary filters, and the canned ones.
 *
 * The problem filters are the part that earns its keep at 242: the question in
 * the week before an event is not "where is Airmail" but "what is still not
 * finished".
 */
const PROBLEMS: { value: Problem; label: string }[] = [
  { value: "no_flag", label: "No flag" },
  { value: "no_skills", label: "No skills" },
  { value: "no_description", label: "No description" },
  { value: "no_hints", label: "No hints" },
  { value: "draft", label: "Still draft" },
  { value: "zone_has_no_boss", label: "Area has no boss" },
  { value: "xp_differs_from_difficulty", label: "XP differs from difficulty" },
];

function FilterBar({
  filters,
  onChange,
  zones,
}: {
  filters: ChallengeFilters;
  onChange: (next: ChallengeFilters) => void;
  zones: ZoneSummary[];
}) {
  const set = <K extends keyof ChallengeFilters>(
    key: K,
    value: ChallengeFilters[K],
  ) => onChange({ ...filters, [key]: value || undefined });

  return (
    <div className="mt-6 flex flex-wrap items-center gap-2 text-sm">
      <input
        value={filters.search ?? ""}
        onChange={(e) => set("search", e.target.value)}
        placeholder="Search title or description…"
        aria-label="Search challenges"
        className="w-64 rounded border border-stone px-3 py-2"
      />
      <select
        value={filters.category_id ?? ""}
        aria-label="Area"
        onChange={(e) => set("category_id", e.target.value)}
        className="rounded border border-stone px-2 py-2"
      >
        <option value="">All areas</option>
        {zones.map((zone) => (
          <option key={zone.category_id} value={zone.category_id}>
            {zone.name}
          </option>
        ))}
      </select>
      <select
        value={filters.state ?? ""}
        aria-label="State"
        onChange={(e) => set("state", e.target.value as ChallengeState)}
        className="rounded border border-stone px-2 py-2"
      >
        <option value="">Any state</option>
        {STATES.map((state) => (
          <option key={state} value={state}>
            {state}
          </option>
        ))}
      </select>
      <select
        value={filters.problem ?? ""}
        aria-label="Problems"
        onChange={(e) => set("problem", e.target.value as Problem)}
        className="rounded border border-stone px-2 py-2"
      >
        <option value="">Anything</option>
        {PROBLEMS.map((problem) => (
          <option key={problem.value} value={problem.value}>
            {problem.label}
          </option>
        ))}
      </select>
      {hasFilters(filters) && (
        <button onClick={() => onChange({})} className="text-muted underline">
          Clear filters
        </button>
      )}
    </div>
  );
}

/**
 * The editor, over the list rather than inside it.
 *
 * Essentials stay open and everything else is behind a collapsed section with a
 * count in its heading, so the seven stacked panels of the old editor become one
 * screen you can read.
 */
function ChallengeDrawer({
  challengeId,
  canWrite,
  onClose,
  onDeleted,
}: {
  challengeId: string;
  canWrite: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [dirty, setDirty] = useState(false);

  // Closing is cheap and reopening is cheaper, so there is no ceremony here —
  // except when there is typed-but-unsaved work, which closing would discard.
  const close = () => {
    if (dirty && !window.confirm("Discard your unsaved changes?")) return;
    setDirty(false);
    onClose();
  };

  return (
    <>
      <div
        className="fixed inset-0 z-20 bg-ink/20"
        onClick={close}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-label="Edit challenge"
        className="fixed inset-y-0 right-0 z-30 w-full max-w-xl overflow-y-auto border-l border-stone bg-parchment shadow-2xl"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-stone bg-parchment px-4 py-3">
          <h2 className="font-semibold">
            Edit challenge
            {dirty && <span className="ml-2 text-xs text-torch">unsaved</span>}
          </h2>
          <button
            onClick={close}
            aria-label="Close editor"
            className="rounded border border-stone px-2 py-1 text-sm"
          >
            Close
          </button>
        </div>
        <ChallengeEditor
          challengeId={challengeId}
          canWrite={canWrite}
          onDeleted={onDeleted}
          onDirtyChange={setDirty}
        />
      </aside>
    </>
  );
}

/** A section that starts closed, with its count in the heading. */
function Collapsible({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="mt-3 rounded border border-stone bg-white/40">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold"
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        {title}
        {count !== undefined && (
          <span className="text-xs font-normal text-muted">({count})</span>
        )}
      </button>
      {open && <div className="border-t border-stone/60 p-3">{children}</div>}
    </section>
  );
}

function CreateChallengeForm() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [category, setCategory] = useState("");

  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: listAdminCategories,
  });

  const create = useMutation({
    mutationFn: () =>
      createChallenge({
        title: title.trim(),
        slug: slug.trim(),
        category: category.trim(),
      }),
    onSuccess: async () => {
      setTitle("");
      setSlug("");
      setCategory("");
      setOpen(false);
      await queryClient.invalidateQueries({
        queryKey: ["admin", "challenges"],
      });
    },
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-4 rounded bg-ink px-4 py-2 text-sm text-parchment"
      >
        New challenge
      </button>
    );
  }

  return (
    <form
      className="mt-4 rounded-lg border border-stone bg-white/60 p-5"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Title
          <input
            required
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              // Suggest a slug, but let it be overridden — it is a stable
              // player-facing identifier, not a display name.
              setSlug(
                event.target.value
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, "-")
                  .replace(/^-|-$/g, ""),
              );
            }}
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          />
        </label>
        <label className="text-sm">
          Slug
          <input
            required
            pattern="[a-z0-9-]+"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
          />
        </label>
        <label className="text-sm sm:col-span-2">
          Category
          <input
            required
            list="category-options"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            placeholder="Type a category — an existing one is reused, a new one is created"
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          />
          <datalist id="category-options">
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.name} />
            ))}
          </datalist>
        </label>
      </div>

      <p className="mt-3 text-xs text-muted">
        Created as a draft. Nothing goes live until you publish it.
      </p>

      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          Create
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-sm underline"
        >
          Cancel
        </button>
      </div>
      <ErrorMessage error={create.error} />
    </form>
  );
}

function ChallengeEditor({
  challengeId,
  canWrite,
  onDeleted,
  onDirtyChange,
}: {
  challengeId: string;
  canWrite: boolean;
  onDeleted: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["admin", "challenge", challengeId],
    queryFn: () => getAdminChallenge(challengeId),
  });

  const reload = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "challenge", challengeId],
    });
    await queryClient.invalidateQueries({ queryKey: ["admin", "challenges"] });
  };

  const changeState = useMutation({
    mutationFn: (state: ChallengeState) =>
      setChallengeState(challengeId, state),
    onSuccess: reload,
  });

  if (detail.isPending) return <Spinner />;
  if (detail.isError) return <ErrorMessage error={detail.error} />;

  const challenge = detail.data;

  return (
    <div className="p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{challenge.title}</h3>
          <p className="text-xs text-muted">
            {challenge.category.name} · {challenge.current_value} XP now ·{" "}
            {challenge.solve_count} solves
          </p>
        </div>
        {canWrite && <DeleteButton challenge={challenge} onDeleted={onDeleted} />}
      </div>

      {canWrite && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">State:</span>
          {STATES.map((state) => (
            <button
              key={state}
              onClick={() => changeState.mutate(state)}
              disabled={changeState.isPending || challenge.state === state}
              className={`rounded px-3 py-1 text-sm ${
                challenge.state === state
                  ? "bg-ink text-parchment"
                  : "border border-stone"
              }`}
            >
              {state}
            </button>
          ))}
        </div>
      )}
      <ErrorMessage error={changeState.error} />

      {/* Essentials open, everything else behind a heading that says how much is
          in it — the seven stacked panels this replaces did not fit on a screen. */}
      {canWrite && (
        <ChallengeSettingsForm
          challenge={challenge}
          onSaved={reload}
          onDirtyChange={onDirtyChange}
        />
      )}

      <Collapsible title="Flags" count={challenge.answers.length}>
        <AnswerRules
          challenge={challenge}
          canWrite={canWrite}
          onChanged={reload}
        />
      </Collapsible>

      {canWrite && (
        <Collapsible title="Hints">
          <HintList challenge={challenge} onChanged={reload} />
        </Collapsible>
      )}
      {canWrite && (
        <Collapsible
          title="Prerequisites"
          count={challenge.prerequisites?.length ?? 0}
        >
          <Prerequisites challenge={challenge} onChanged={reload} />
        </Collapsible>
      )}
      {canWrite && (
        <Collapsible title="Container">
          <ContainerAssignment challenge={challenge} onSaved={reload} />
        </Collapsible>
      )}
    </div>
  );
}

/**
 * Delete, in the drawer header rather than at the foot of a long scroll.
 *
 * The old placement cost a click into the row, a scroll past seven sections and
 * then two more clicks. The distance was the problem, not the absence of a
 * second confirmation — so this is one confirm, and it names the challenge and
 * what goes with it rather than asking "are you sure".
 */
function DeleteButton({
  challenge,
  onDeleted,
}: {
  challenge: AdminChallengeDetail;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => deleteChallenge(challenge.id),
    onSuccess: onDeleted,
  });

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        className="shrink-0 rounded border border-torch px-3 py-1 text-sm text-torch hover:bg-torch/10"
      >
        Delete
      </button>
    );
  }

  return (
    <div className="shrink-0 rounded border border-torch bg-parchment p-3 text-sm">
      <p>
        Delete <strong>{challenge.title}</strong>, with its flags and hints?
      </p>
      <p className="mt-1 text-xs text-muted">
        If it is the last challenge in {challenge.category.name}, that area goes
        too.
      </p>
      <div className="mt-2 flex justify-end gap-2">
        <button
          onClick={() => setConfirming(false)}
          className="rounded border border-stone px-3 py-1"
        >
          Cancel
        </button>
        <button
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="rounded bg-torch px-3 py-1 text-parchment disabled:opacity-50"
        >
          {remove.isPending ? "Deleting…" : "Delete"}
        </button>
      </div>
      <ErrorMessage error={remove.error} />
    </div>
  );
}

function AnswerRules({
  challenge,
  canWrite,
  onChanged,
}: {
  challenge: {
    id: string;
    answers: {
      id: string;
      match_type: MatchType;
      value: string;
      label: string | null;
    }[];
  };
  canWrite: boolean;
  onChanged: () => Promise<void>;
}) {
  const [matchType, setMatchType] = useState<MatchType>("exact");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [candidate, setCandidate] = useState("");

  const add = useMutation({
    mutationFn: () =>
      addAnswer(challenge.id, {
        match_type: matchType,
        value,
        label: label.trim() || undefined,
      }),
    onSuccess: async () => {
      setValue("");
      setLabel("");
      await onChanged();
    },
  });

  const remove = useMutation({
    mutationFn: (answerId: string) => deleteAnswer(challenge.id, answerId),
    onSuccess: onChanged,
  });

  const test = useMutation({
    mutationFn: () => testAnswer(challenge.id, candidate),
  });

  const hint = MATCH_TYPES.find((type) => type.value === matchType)?.hint;

  return (
    <section className="mt-5">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Accepted answers ({challenge.answers.length})
      </h3>
      <p className="mt-1 text-xs text-muted">
        A submission is correct if any one of these matches.
      </p>

      <ul className="mt-3 flex flex-col gap-2">
        {challenge.answers.map((answer) => (
          <li
            key={answer.id}
            className="flex items-center gap-3 rounded border border-stone bg-parchment px-3 py-2"
          >
            <span className="rounded bg-stone px-2 py-0.5 text-xs">
              {answer.match_type}
            </span>
            <code className="flex-1 truncate text-sm">{answer.value}</code>
            {answer.label && (
              <span className="text-xs text-muted">{answer.label}</span>
            )}
            {canWrite && (
              <button
                onClick={() => remove.mutate(answer.id)}
                className="text-xs text-torch underline"
              >
                Remove
              </button>
            )}
          </li>
        ))}
        {challenge.answers.length === 0 && (
          <li className="text-sm text-torch">
            No answers yet — nobody can solve this challenge.
          </li>
        )}
      </ul>

      {canWrite && (
        <>
          <form
            className="mt-4 grid gap-2 sm:grid-cols-[10rem_1fr_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              add.mutate();
            }}
          >
            <select
              value={matchType}
              onChange={(event) =>
                setMatchType(event.target.value as MatchType)
              }
              className="rounded border border-stone px-3 py-2 text-sm"
              aria-label="Match type"
            >
              {MATCH_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
            <input
              required
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={hint}
              aria-label="Answer value"
              className="rounded border border-stone px-3 py-2 font-mono text-sm"
            />
            <button
              type="submit"
              disabled={add.isPending}
              className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
            >
              Add
            </button>
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Note (optional) — e.g. accepts the British spelling"
              aria-label="Answer note"
              className="rounded border border-stone px-3 py-2 text-sm sm:col-span-3"
            />
          </form>
          <ErrorMessage error={add.error ?? remove.error} />

          <div className="mt-4 rounded border border-dashed border-stone p-3">
            <h4 className="text-sm font-medium">Try an answer</h4>
            <p className="mt-1 text-xs text-muted">
              Checks against the rules above without recording anything. Test a
              pattern here rather than discovering it mid-event.
            </p>
            <form
              className="mt-2 flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                test.mutate();
              }}
            >
              <input
                value={candidate}
                onChange={(event) => setCandidate(event.target.value)}
                aria-label="Candidate answer"
                className="flex-1 rounded border border-stone px-3 py-2 font-mono text-sm"
                placeholder="What would a player type?"
              />
              <button
                type="submit"
                disabled={test.isPending || candidate === ""}
                className="rounded border border-ink px-4 py-2 text-sm disabled:opacity-50"
              >
                Test
              </button>
            </form>

            {test.data && (
              <p role="status" className="mt-2 text-sm">
                {test.data.correct ? (
                  <span>
                    Accepted
                    {test.data.matched_label &&
                      ` by “${test.data.matched_label}”`}
                    .
                  </span>
                ) : (
                  <span className="text-torch">No rule matches that.</span>
                )}
                {test.data.errors.length > 0 && (
                  <span className="mt-1 block text-xs text-torch">
                    Rule problems: {test.data.errors.join("; ")}
                  </span>
                )}
              </p>
            )}
            <ErrorMessage error={test.error} />
          </div>
        </>
      )}
    </section>
  );
}

const DIFFICULTIES: Difficulty[] = [
  "very_easy",
  "easy",
  "medium",
  "hard",
  "very_hard",
  "nearly_impossible",
];

/** Difficulty only *suggests* the XP now (spec 040) — these are the numbers a
 *  blank field falls back to, shown so the ladder stays visible while choosing. */
export const DIFFICULTY_XP: Record<Difficulty, number> = {
  very_easy: 50,
  easy: 100,
  medium: 150,
  hard: 200,
  very_hard: 250,
  nearly_impossible: 500,
};

export const difficultyLabel = (d: Difficulty) =>
  d.replace(/_/g, " ").replace(/\w/g, (c) => c.toUpperCase());

function ChallengeSettingsForm({
  challenge,
  onSaved,
  onDirtyChange,
}: {
  challenge: AdminChallengeDetail;
  onSaved: () => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [form, setForm] = useState<UpdateChallengeInput>({
    body: challenge.body,
    difficulty: challenge.difficulty,
    initial_points: challenge.initial_points,
    minimum_points: challenge.minimum_points,
    scoring: challenge.scoring,
    decay_basis: challenge.decay_basis,
    decay_threshold: challenge.decay_threshold,
    max_attempts: challenge.max_attempts,
    boss_tier: challenge.boss_tier ?? null,
  });
  // Typed-but-unsaved work is the one thing closing the drawer could throw
  // away, so the drawer is told about it.
  const [dirty, setDirty] = useState(false);
  const markDirty = (next: boolean) => {
    setDirty(next);
    onDirtyChange?.(next);
  };

  const set = <K extends keyof UpdateChallengeInput>(
    key: K,
    value: UpdateChallengeInput[K],
  ) => {
    markDirty(true);
    setForm((f) => ({ ...f, [key]: value }));
  };

  const save = useMutation({
    mutationFn: () => updateChallenge(challenge.id, form),
    onSuccess: async () => {
      markDirty(false);
      await onSaved();
    },
  });

  return (
    <form
      className="mt-4 rounded border border-stone bg-white/40 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Settings
      </h3>

      <label className="mt-3 block text-sm">
        Description / task
        <textarea
          value={form.body ?? ""}
          onChange={(e) => set("body", e.target.value)}
          rows={4}
          placeholder="What should the player do?"
          className="mt-1 w-full rounded border border-stone px-3 py-2"
        />
      </label>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          Difficulty
          <select
            value={form.difficulty}
            onChange={(e) => set("difficulty", e.target.value as Difficulty)}
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          >
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {difficultyLabel(d)} — suggests {DIFFICULTY_XP[d]} XP
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Boss
          <select
            value={form.boss_tier ?? ""}
            onChange={(e) =>
              set("boss_tier", (e.target.value || null) as BossTier | null)
            }
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          >
            {/* One boss per zone; the server refuses a second and names the
                challenge already holding the slot. */}
            <option value="">Not a boss</option>
            {BOSS_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {BOSS_TIER_LABEL[tier]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Scoring
          <select
            value={form.scoring}
            onChange={(e) =>
              set("scoring", e.target.value as "dynamic" | "static")
            }
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          >
            <option value="dynamic">Dynamic (decays)</option>
            <option value="static">Static (fixed)</option>
          </select>
        </label>
        <label className="text-sm">
          Max attempts
          <input
            type="number"
            min={1}
            value={form.max_attempts ?? ""}
            onChange={(e) =>
              set(
                "max_attempts",
                e.target.value === "" ? null : Number(e.target.value),
              )
            }
            placeholder="unlimited"
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          />
        </label>
        {/* Typed, not derived (spec 040). Changing difficulty above leaves this
            alone — relabelling a challenge must not move what it pays. */}
        <label className="text-sm">
          XP
          <input
            type="number"
            min={1}
            value={form.initial_points ?? ""}
            onChange={(e) =>
              set(
                "initial_points",
                e.target.value === "" ? undefined : Number(e.target.value),
              )
            }
            placeholder={String(DIFFICULTY_XP[form.difficulty ?? challenge.difficulty])}
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          />
        </label>
        {form.scoring === "dynamic" && (
          <label className="text-sm">
            Minimum XP
            <input
              type="number"
              min={1}
              value={form.minimum_points ?? ""}
              onChange={(e) =>
                set(
                  "minimum_points",
                  e.target.value === "" ? null : Number(e.target.value),
                )
              }
              placeholder="40% of XP"
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
        )}
        {form.scoring === "dynamic" && (
          <>
            <label className="text-sm">
              Decays per
              <select
                value={form.decay_basis}
                onChange={(e) =>
                  set("decay_basis", e.target.value as "players" | "teams")
                }
                className="mt-1 w-full rounded border border-stone px-3 py-2"
              >
                <option value="players">Players</option>
                <option value="teams">Teams</option>
              </select>
            </label>
            <label className="text-sm">
              Decay after N solves
              <input
                type="number"
                min={2}
                value={form.decay_threshold ?? 40}
                onChange={(e) => set("decay_threshold", Number(e.target.value))}
                className="mt-1 w-full rounded border border-stone px-3 py-2"
              />
            </label>
          </>
        )}
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          type="submit"
          disabled={save.isPending || !dirty}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          Save settings
        </button>
        {dirty && <span className="text-sm text-torch">Unsaved changes</span>}
        {!dirty && save.isSuccess && (
          <span className="text-sm text-muted">Saved.</span>
        )}
      </div>
      <ErrorMessage error={save.error} />

      <div className="mt-5 border-t border-stone pt-4">
        <ChallengeSkills challenge={challenge} />
      </div>
    </form>
  );
}

/** Which skills this challenge feeds. Saved separately from the settings form,
 *  because it is a different decision made at a different time. */
function ChallengeSkills({ challenge }: { challenge: AdminChallengeDetail }) {
  const queryClient = useQueryClient();
  const skills = useQuery({ queryKey: ["admin", "skills"], queryFn: listSkills });
  const assigned = useQuery({
    queryKey: ["admin", "challenge-skills", challenge.id],
    queryFn: () => getChallengeSkills(challenge.id),
  });

  const save = useMutation({
    mutationFn: (ids: string[]) => setChallengeSkills(challenge.id, ids),
    onSuccess: (ids) =>
      queryClient.setQueryData(["admin", "challenge-skills", challenge.id], ids),
  });

  if (skills.isPending || assigned.isPending) return <Spinner />;
  if (skills.isError) return <ErrorMessage error={skills.error} />;

  return (
    <>
      <SkillPicker
        skills={skills.data}
        categoryId={challenge.category.id}
        selected={save.variables ?? assigned.data ?? []}
        disabled={save.isPending}
        onChange={(ids) => save.mutate(ids)}
      />
      <ErrorMessage error={save.error} />
    </>
  );
}

function HintList({
  challenge,
  onChanged,
}: {
  challenge: AdminChallengeDetail;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const hints = useQuery({
    queryKey: ["admin", "hints", challenge.id],
    queryFn: () => listHints(challenge.id),
  });
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [cost, setCost] = useState(50);

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["admin", "hints", challenge.id],
    });

  const add = useMutation({
    mutationFn: () =>
      createHint(challenge.id, {
        title: title.trim(),
        body: body.trim(),
        cost,
      }),
    onSuccess: async () => {
      setTitle("");
      setBody("");
      await invalidate();
      await onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteHint(challenge.id, id),
    onSuccess: invalidate,
  });
  const setCostFor = useMutation({
    mutationFn: ({ id, next }: { id: string; next: number }) =>
      updateHint(challenge.id, id, { cost: next }),
    onSuccess: invalidate,
  });

  return (
    <section className="mt-4 rounded border border-stone bg-white/40 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Hints
      </h3>
      <ul className="mt-2 space-y-2">
        {(hints.data ?? []).map((hint: AdminHint) => (
          <li
            key={hint.id}
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <span className="flex-1">
              <span className="font-medium">{hint.title}</span>
              <span className="block text-muted">{hint.body}</span>
            </span>
            <label className="text-xs text-muted">
              cost
              <input
                type="number"
                min={0}
                defaultValue={hint.cost}
                onBlur={(e) => {
                  const next = Number(e.target.value);
                  if (next !== hint.cost)
                    setCostFor.mutate({ id: hint.id, next });
                }}
                className="ml-1 w-20 rounded border border-stone px-2 py-1"
              />
            </label>
            <button
              onClick={() => remove.mutate(hint.id)}
              className="text-xs text-torch underline"
            >
              Delete
            </button>
          </li>
        ))}
        {(hints.data ?? []).length === 0 && (
          <li className="text-sm text-muted">No hints yet.</li>
        )}
      </ul>

      <form
        className="mt-3 grid gap-2 sm:grid-cols-[1fr_2fr_auto_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Hint title"
          className="rounded border border-stone px-2 py-1 text-sm"
        />
        <input
          required
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Hint text (withheld until unlocked)"
          className="rounded border border-stone px-2 py-1 text-sm"
        />
        <input
          type="number"
          min={0}
          value={cost}
          onChange={(e) => setCost(Number(e.target.value))}
          className="w-24 rounded border border-stone px-2 py-1 text-sm"
        />
        <button
          type="submit"
          disabled={add.isPending}
          className="rounded bg-ink px-3 py-1 text-sm text-parchment disabled:opacity-50"
        >
          Add hint
        </button>
      </form>
      <ErrorMessage error={add.error} />
    </section>
  );
}

function ContainerAssignment({
  challenge,
  onSaved,
}: {
  challenge: AdminChallengeDetail;
  onSaved: () => Promise<void>;
}) {
  const templates = useQuery({
    queryKey: ["admin", "templates"],
    queryFn: listTemplates,
  });
  const assign = useMutation({
    mutationFn: (templateId: string | null) =>
      updateChallenge(challenge.id, { container_template_id: templateId }),
    onSuccess: onSaved,
  });

  return (
    <section className="mt-4 rounded border border-stone bg-white/40 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Live container
      </h3>
      <label className="mt-2 block text-sm">
        Template
        <select
          value={challenge.container_template_id ?? ""}
          onChange={(e) =>
            assign.mutate(e.target.value === "" ? null : e.target.value)
          }
          className="mt-1 w-full rounded border border-stone px-3 py-2"
        >
          <option value="">None (static challenge)</option>
          {(templates.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.image}:{t.image_tag})
            </option>
          ))}
        </select>
      </label>
      <p className="mt-2 text-xs text-muted">
        Manage templates on the Containers page. Assigning one lets players spin
        up their own instance once the challenge is published.
      </p>
      <ErrorMessage error={assign.error} />
    </section>
  );
}

function Prerequisites({
  challenge,
  onChanged,
}: {
  challenge: AdminChallengeDetail;
  onChanged: () => Promise<void>;
}) {
  const all = useQuery({
    queryKey: ["admin", "challenges"],
    queryFn: () => listAdminChallenges(),
  });
  const [pick, setPick] = useState("");

  const add = useMutation({
    mutationFn: () => addPrerequisite(challenge.id, pick),
    onSuccess: async () => {
      setPick("");
      await onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => removePrerequisite(challenge.id, id),
    onSuccess: onChanged,
  });

  const options = (all.data ?? []).filter(
    (c) =>
      c.id !== challenge.id &&
      !challenge.prerequisites.some((p) => p.challenge_id === c.id),
  );

  return (
    <section className="mt-4 rounded border border-stone bg-white/40 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Unlock requirements
      </h3>
      <p className="mt-1 text-xs text-muted">
        Players must solve all of these before this challenge unlocks for them.
      </p>
      <ul className="mt-2 space-y-1">
        {challenge.prerequisites.map((p) => (
          <li key={p.challenge_id} className="flex items-center gap-2 text-sm">
            <span className="flex-1">{p.title}</span>
            <button
              onClick={() => remove.mutate(p.challenge_id)}
              className="text-xs text-torch underline"
            >
              Remove
            </button>
          </li>
        ))}
        {challenge.prerequisites.length === 0 && (
          <li className="text-sm text-muted">
            No prerequisites — unlocked for everyone.
          </li>
        )}
      </ul>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (pick) add.mutate();
        }}
      >
        <select
          value={pick}
          onChange={(e) => setPick(e.target.value)}
          className="flex-1 rounded border border-stone px-3 py-2 text-sm"
        >
          <option value="">Require a challenge…</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!pick || add.isPending}
          className="rounded bg-ink px-3 py-1 text-sm text-parchment disabled:opacity-50"
        >
          Add
        </button>
      </form>
      <ErrorMessage error={add.error} />
    </section>
  );
}
