import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  addAnswer,
  addPrerequisite,
  createChallenge,
  deleteChallenge,
  deleteAnswer,
  getAdminChallenge,
  listAdminCategories,
  listAdminChallenges,
  removePrerequisite,
  setChallengeState,
  testAnswer,
  updateChallenge,
  type AdminChallengeDetail,
  type UpdateChallengeInput,
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

export default function AdminChallengesPage() {
  const { me } = useSession();
  const [selected, setSelected] = useState<string | null>(null);

  const challenges = useQuery({
    queryKey: ["admin", "challenges"],
    queryFn: listAdminChallenges,
  });

  const canWrite = me?.capabilities.administer ?? false;

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Challenges</h1>
        <span className="text-muted">{challenges.data?.length ?? 0} total</span>
      </header>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          You have read-only access. Only admins can change challenges.
        </p>
      )}

      {canWrite && <CreateChallengeForm />}

      {challenges.isPending ? (
        <Spinner />
      ) : (
        <ul className="mt-6 flex flex-col gap-2">
          {(challenges.data ?? []).map((challenge) => (
            <li
              key={challenge.id}
              className="rounded-lg border border-stone bg-white/60"
            >
              <button
                onClick={() =>
                  setSelected(selected === challenge.id ? null : challenge.id)
                }
                className="flex w-full items-center gap-3 p-4 text-left"
                aria-expanded={selected === challenge.id}
              >
                <span className="flex-1">
                  <span className="font-medium">{challenge.title}</span>
                  <span className="block text-sm text-muted">
                    {challenge.category.name} · {challenge.current_value} pts ·{" "}
                    {challenge.solve_count} solves
                  </span>
                </span>
                <StateBadge
                  state={challenge.state}
                  effective={challenge.effective_state}
                />
              </button>

              {selected === challenge.id && (
                <ChallengeEditor
                  challengeId={challenge.id}
                  canWrite={canWrite}
                  // Collapse the panel and refresh the list: the challenge it
                  // was showing no longer exists.
                  onDeleted={() => {
                    setSelected(null);
                    void challenges.refetch();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function StateBadge({
  state,
  effective,
}: {
  state: ChallengeState;
  effective: ChallengeState;
}) {
  // Both are shown when they disagree: a published challenge whose release time
  // has not arrived is a situation an admin needs to see at a glance.
  const differs = state !== effective;
  return (
    <span className="shrink-0 text-xs">
      <span className="rounded bg-stone px-2 py-0.5">{state}</span>
      {differs && <span className="ml-1 text-muted">→ now {effective}</span>}
    </span>
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
}: {
  challengeId: string;
  canWrite: boolean;
  onDeleted: () => void;
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
    <div className="border-t border-stone p-4">
      {canWrite && (
        <div className="flex flex-wrap items-center gap-2">
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

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted">Value now</dt>
          <dd>{challenge.current_value}</dd>
        </div>
        <div>
          <dt className="text-muted">Solves</dt>
          <dd>{challenge.solve_count}</dd>
        </div>
      </dl>

      {canWrite && (
        <ChallengeSettingsForm challenge={challenge} onSaved={reload} />
      )}

      <AnswerRules
        challenge={challenge}
        canWrite={canWrite}
        onChanged={reload}
      />

      {canWrite && <HintList challenge={challenge} onChanged={reload} />}
      {canWrite && (
        <ContainerAssignment challenge={challenge} onSaved={reload} />
      )}
      {canWrite && <Prerequisites challenge={challenge} onChanged={reload} />}
      {canWrite && <DangerZone challenge={challenge} onDeleted={onDeleted} />}
    </div>
  );
}

/**
 * Deleting a challenge takes its solves, hints and answers with it, and prunes
 * the category if that leaves it empty — which is also how an unwanted area goes
 * away. Irreversible, so it asks first, and the confirmation names the challenge
 * rather than saying "are you sure": a generic prompt gets clicked through.
 */
function DangerZone({
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

  return (
    <section className="mt-8 rounded border border-torch/40 bg-white/40 p-4">
      <h3 className="text-sm font-semibold">Delete challenge</h3>
      <p className="mt-1 text-xs text-muted">
        Removes it along with its answers, hints and solves. If this is the last
        challenge in {challenge.category.name}, that area goes too. Cannot be
        undone.
      </p>

      {confirming ? (
        <div className="mt-3 rounded border border-stone bg-parchment p-3">
          <p className="text-sm">
            Delete <strong>{challenge.title}</strong>?
          </p>
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="rounded bg-torch px-4 py-2 text-sm font-medium text-ink disabled:opacity-50"
            >
              {remove.isPending ? "Deleting…" : "Yes, delete it"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="rounded border border-stone px-4 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          className="mt-3 rounded border border-torch px-4 py-2 text-sm hover:bg-torch/10"
        >
          Delete challenge
        </button>
      )}
      <ErrorMessage error={remove.error} />
    </section>
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

/** Difficulty derives the XP, so the editor shows what each tier is worth. */
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
}: {
  challenge: AdminChallengeDetail;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<UpdateChallengeInput>({
    body: challenge.body,
    difficulty: challenge.difficulty,
    scoring: challenge.scoring,
    decay_basis: challenge.decay_basis,
    decay_threshold: challenge.decay_threshold,
    max_attempts: challenge.max_attempts,
  });
  const set = <K extends keyof UpdateChallengeInput>(
    key: K,
    value: UpdateChallengeInput[K],
  ) => setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () => updateChallenge(challenge.id, form),
    onSuccess: onSaved,
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
                {difficultyLabel(d)} — {DIFFICULTY_XP[d]} XP
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
        {/* Derived from difficulty (spec 018), so shown rather than typed —
            an inverted floor-above-ceiling is now unreachable. */}
        <div className="text-sm">
          <span className="block">XP</span>
          <p className="mt-1 rounded border border-dashed border-stone px-3 py-2 text-muted">
            {DIFFICULTY_XP[form.difficulty ?? challenge.difficulty]} ceiling,
            floor {Math.floor(DIFFICULTY_XP[form.difficulty ?? challenge.difficulty] * 0.4)}
            <span className="block text-xs">set by difficulty</span>
          </p>
        </div>
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
          disabled={save.isPending}
          className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
        >
          Save settings
        </button>
        {save.isSuccess && <span className="text-sm text-muted">Saved.</span>}
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
    queryFn: listAdminChallenges,
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
