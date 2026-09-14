import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { listSkills } from "../api/adminSkills";

import {
  bulkEdit,
  previewBulkDelete,
  type BulkAction,
  type BulkResult,
  type DeletePreview,
} from "../api/adminChallenges";
import type { ChallengeState, Difficulty } from "../api/challenges";
import ErrorMessage from "./ErrorMessage";

/**
 * Bulk operations over the current selection (spec 042).
 *
 * The page is used to *set an event up*, so the design goal is low friction: one
 * confirm where the consequence is real, none where it is not. Delete gets a
 * dialog, and only because two of its consequences are invisible from the
 * selection — which rows cannot be deleted, and which zones go with them.
 */

const STATES: ChallengeState[] = ["draft", "hidden", "locked", "published"];
const DIFFICULTIES: Difficulty[] = [
  "very_easy",
  "easy",
  "medium",
  "hard",
  "very_hard",
  "nearly_impossible",
];

export default function BulkToolbar({
  selected,
  onClear,
  matchingCount,
  onSelectAllMatching,
}: {
  selected: string[];
  onClear: () => void;
  matchingCount: number;
  onSelectAllMatching: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState<DeletePreview | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);
  const [xp, setXp] = useState("");
  const [releaseAt, setReleaseAt] = useState("");

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "challenges"] });
    await queryClient.invalidateQueries({ queryKey: ["admin", "zones"] });
  };

  const run = useMutation({
    mutationFn: ({ action, value }: { action: BulkAction; value?: unknown }) =>
      bulkEdit(selected, action, value),
    onSuccess: async (data) => {
      setResult(data);
      setConfirming(null);
      await refresh();
      // Cleared on completion: the rows it referred to have changed, and a
      // stale selection is how the next action hits the wrong thing.
      onClear();
    },
  });

  const preview = useMutation({
    mutationFn: () => previewBulkDelete(selected),
    onSuccess: setConfirming,
  });

  if (selected.length === 0 && !result) return null;

  return (
    <div className="sticky bottom-0 z-10 mt-4 rounded border border-stone bg-white/95 p-3 shadow-lg">
      {selected.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <strong>{selected.length} selected</strong>
            {matchingCount > selected.length && (
              <button onClick={onSelectAllMatching} className="underline">
                Select all {matchingCount} matching
              </button>
            )}
            <button onClick={onClear} className="text-muted underline">
              Clear
            </button>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <Picker
              label="Set state"
              options={STATES}
              disabled={run.isPending}
              onPick={(value) => run.mutate({ action: "set_state", value })}
            />
            <Picker
              label="Set difficulty"
              options={DIFFICULTIES}
              disabled={run.isPending}
              onPick={(value) => run.mutate({ action: "set_difficulty", value })}
            />
            <span className="flex items-center gap-1">
              <input
                value={xp}
                onChange={(e) => setXp(e.target.value)}
                placeholder="XP, or +25 / -10%"
                aria-label="Set XP"
                className="w-36 rounded border border-stone px-2 py-1"
              />
              <button
                disabled={!xp || run.isPending}
                onClick={() => {
                  run.mutate({ action: "set_xp", value: xp });
                  setXp("");
                }}
                className="rounded border border-stone px-2 py-1 disabled:opacity-40"
              >
                Apply
              </button>
            </span>
            <SkillPicker
              disabled={run.isPending}
              onApply={(action, names) => run.mutate({ action, value: names })}
            />
            <span className="flex items-center gap-1">
              <input
                type="datetime-local"
                value={releaseAt}
                onChange={(e) => setReleaseAt(e.target.value)}
                aria-label="Set release time"
                className="rounded border border-stone px-2 py-1"
              />
              <button
                disabled={run.isPending}
                onClick={() => {
                  // An empty field clears the schedule, which is the other half
                  // of setting one across a timed wave.
                  run.mutate({
                    action: "set_release_at",
                    value: releaseAt || null,
                  });
                  setReleaseAt("");
                }}
                className="rounded border border-stone px-2 py-1 disabled:opacity-40"
              >
                {releaseAt ? "Schedule" : "Clear schedule"}
              </button>
            </span>
            <button
              disabled={preview.isPending || run.isPending}
              onClick={() => preview.mutate()}
              className="rounded border border-torch px-3 py-1 text-torch"
            >
              Delete…
            </button>
          </div>
        </>
      )}

      <ErrorMessage error={run.error ?? preview.error} />

      {confirming && (
        <DeleteConfirm
          preview={confirming}
          pending={run.isPending}
          onCancel={() => setConfirming(null)}
          onConfirm={() => run.mutate({ action: "delete" })}
        />
      )}

      {result && <Result result={result} onDismiss={() => setResult(null)} />}
    </div>
  );
}

/**
 * Add or remove, never replace. Applying a shared skill across an area is the
 * real use; replace would be the same gesture with a silent wipe of every
 * per-challenge mapping already attached.
 */
function SkillPicker({
  disabled,
  onApply,
}: {
  disabled: boolean;
  onApply: (action: BulkAction, names: string[]) => void;
}) {
  const skills = useQuery({ queryKey: ["admin", "skills"], queryFn: listSkills });
  const [name, setName] = useState("");

  return (
    <span className="flex items-center gap-1">
      <select
        value={name}
        disabled={disabled}
        aria-label="Skill"
        onChange={(e) => setName(e.target.value)}
        className="rounded border border-stone px-2 py-1"
      >
        <option value="">Skill…</option>
        {(skills.data ?? []).map((skill) => (
          <option key={skill.id} value={skill.name}>
            {skill.name}
          </option>
        ))}
      </select>
      <button
        disabled={!name || disabled}
        onClick={() => onApply("add_skills", [name])}
        className="rounded border border-stone px-2 py-1 disabled:opacity-40"
      >
        Add
      </button>
      <button
        disabled={!name || disabled}
        onClick={() => onApply("remove_skills", [name])}
        className="rounded border border-stone px-2 py-1 disabled:opacity-40"
      >
        Remove
      </button>
    </span>
  );
}

function Picker({
  label,
  options,
  disabled,
  onPick,
}: {
  label: string;
  options: string[];
  disabled: boolean;
  onPick: (value: string) => void;
}) {
  return (
    <select
      value=""
      disabled={disabled}
      aria-label={label}
      onChange={(e) => {
        if (e.target.value) onPick(e.target.value);
        e.target.value = "";
      }}
      className="rounded border border-stone px-2 py-1"
    >
      <option value="">{label}…</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {option.replace(/_/g, " ")}
        </option>
      ))}
    </select>
  );
}

/**
 * The dialog's job is to state the blast radius, not to make you prove you meant
 * it. Once it has said what will happen, a second confirmation adds nothing.
 */
function DeleteConfirm({
  preview,
  pending,
  onCancel,
  onConfirm,
}: {
  preview: DeletePreview;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-label="Confirm delete"
      className="mt-3 rounded border border-torch bg-parchment p-3 text-sm"
    >
      <p className="font-semibold">
        Delete {preview.deletable}{" "}
        {preview.deletable === 1 ? "challenge" : "challenges"}?
      </p>
      <ul className="mt-2 list-disc pl-5 text-muted">
        {preview.zones_emptied.map((zone) => (
          <li key={zone.category_id}>
            This empties <strong>{zone.name}</strong>, so that area will be
            deleted too.
            {zone.skills_orphaned > 0 && (
              <>
                {" "}
                Its {zone.skills_orphaned}{" "}
                {zone.skills_orphaned === 1 ? "skill is" : "skills are"} kept but
                will lose their area grouping.
              </>
            )}
          </li>
        ))}
        {preview.blocked.length > 0 && (
          <li>
            {preview.blocked.length} cannot be deleted — players have solved
            them. They will be skipped.
          </li>
        )}
      </ul>
      <div className="mt-3 flex justify-end gap-2">
        <button onClick={onCancel} className="rounded border border-stone px-3 py-1">
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={pending || preview.deletable === 0}
          className="rounded bg-torch px-3 py-1 text-parchment disabled:opacity-40"
        >
          {pending ? "Deleting…" : `Delete ${preview.deletable}`}
        </button>
      </div>
    </div>
  );
}

function Result({
  result,
  onDismiss,
}: {
  result: BulkResult;
  onDismiss: () => void;
}) {
  return (
    <div role="status" className="mt-3 rounded border border-stone bg-white/60 p-3 text-sm">
      <div className="flex items-baseline justify-between">
        <span>
          <strong>{result.succeeded}</strong> changed
          {result.failed > 0 && <>, {result.failed} skipped</>}.
          {result.categories_deleted.length > 0 && (
            <> Areas removed: {result.categories_deleted.join(", ")}.</>
          )}
        </span>
        <button onClick={onDismiss} className="text-muted underline">
          Dismiss
        </button>
      </div>
      {/* The reasons, not a bare "some failed" — each one says what to do
          instead. */}
      {result.results
        .filter((item) => !item.ok)
        .map((item) => (
          <p key={item.challenge_id} className="mt-1 text-xs text-muted">
            {item.reason}
          </p>
        ))}
    </div>
  );
}
