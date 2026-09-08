import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createClass,
  deleteClass,
  listClasses,
  updateClass,
} from "../api/adminClasses";
import { listSkills, type Skill } from "../api/adminSkills";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Character classes (spec 016) — the roster players choose from once they reach
 * the unlock level. Each class can point at an affinity skill, which drives the
 * System AI's suggested-class nudge. Twin of the admin Skills page; a class never
 * touches scoring.
 */
export default function AdminClassesPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const classes = useQuery({ queryKey: ["admin", "classes"], queryFn: listClasses });
  const skills = useQuery({ queryKey: ["admin", "skills"], queryFn: listSkills });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "classes"] });

  const [newName, setNewName] = useState("");
  const create = useMutation({
    mutationFn: () => createClass({ name: newName.trim() }),
    onSuccess: () => {
      setNewName("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (classId: string) => deleteClass(classId),
    onSuccess: invalidate,
  });
  const setAffinity = useMutation({
    mutationFn: (input: { classId: string; skillId: string | null }) =>
      updateClass(input.classId, { affinity_skill_id: input.skillId }),
    onSuccess: invalidate,
  });

  if (classes.isPending || skills.isPending) return <Spinner />;
  if (classes.isError) return <ErrorMessage error={classes.error} />;
  if (skills.isError) return <ErrorMessage error={skills.error} />;

  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Classes</h1>
      <p className="mt-2 text-sm text-muted">
        The archetypes players pick from. A class's affinity skill is what the
        System AI reads to suggest it — it has no effect on scoring.
      </p>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          Read-only — only admins can change classes.
        </p>
      )}

      {classes.data.length === 0 ? (
        <p className="mt-6 text-sm text-muted">No classes yet.</p>
      ) : (
        <ul className="mt-6 space-y-2">
          {classes.data.map((klass) => (
            <li
              key={klass.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded border border-stone bg-white/40 px-4 py-2"
            >
              <span className="font-medium">{klass.name}</span>
              <span className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-muted">
                  Affinity
                  <select
                    aria-label={`Affinity skill for ${klass.name}`}
                    value={klass.affinity_skill_id ?? ""}
                    disabled={!canWrite || setAffinity.isPending}
                    onChange={(e) =>
                      setAffinity.mutate({
                        classId: klass.id,
                        skillId: e.target.value || null,
                      })
                    }
                    className="rounded border border-stone px-2 py-1 text-sm"
                  >
                    <option value="">— none —</option>
                    {skills.data.map((skill: Skill) => (
                      <option key={skill.id} value={skill.id}>
                        {skill.name}
                      </option>
                    ))}
                  </select>
                </label>
                {canWrite && (
                  <button
                    onClick={() => remove.mutate(klass.id)}
                    disabled={remove.isPending}
                    className="text-sm text-muted hover:text-ink hover:underline disabled:opacity-50"
                  >
                    Delete
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {canWrite && (
        <form
          className="mt-4 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) create.mutate();
          }}
        >
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New class name"
            aria-label="New class name"
            className="flex-1 rounded border border-stone px-3 py-2"
          />
          <button
            type="submit"
            disabled={create.isPending || !newName.trim()}
            className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
          >
            Add class
          </button>
        </form>
      )}
      <ErrorMessage error={create.error ?? remove.error ?? setAffinity.error} />
    </main>
  );
}
