import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createSkill,
  deleteSkill,
  listCategories,
  listSkills,
  setCategoryAbility,
  type Ability,
} from "../api/adminSkills";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Skills, and the category→ability map (spec 018).
 *
 * Skills attach to individual *challenges* (in the challenge editor), not to
 * categories — a challenge feeds every skill on it in full. Categories instead
 * feed one of the six abilities, which is what partitions a player's XP into a
 * stat block, so every category must have one.
 */
const ABILITIES: [Ability, string][] = [
  ["str", "Strength"],
  ["dex", "Dexterity"],
  ["con", "Constitution"],
  ["int", "Intelligence"],
  ["wis", "Wisdom"],
  ["cha", "Charisma"],
];

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

  const [newName, setNewName] = useState("");
  const create = useMutation({
    mutationFn: () => createSkill({ name: newName.trim() }),
    onSuccess: () => {
      setNewName("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (skillId: string) => deleteSkill(skillId),
    onSuccess: invalidate,
  });
  const map = useMutation({
    mutationFn: (input: { categoryId: string; ability: Ability }) =>
      setCategoryAbility(input.categoryId, input.ability),
    onSuccess: invalidate,
  });

  if (skills.isPending || categories.isPending) return <Spinner />;
  if (skills.isError) return <ErrorMessage error={skills.error} />;
  if (categories.isError) return <ErrorMessage error={categories.error} />;

  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Skills</h1>
      <p className="mt-2 text-sm text-muted">
        Skills attach to individual challenges, and solving one feeds every skill
        on it. Categories feed an <strong>ability</strong> instead — that mapping
        is below, and every category needs one.
      </p>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          Read-only — only admins can change skills.
        </p>
      )}

      <section className="mt-6">
        <h2 className="text-lg font-semibold">Skills</h2>
        {skills.data.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No skills yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {skills.data.map((skill) => (
              <li
                key={skill.id}
                className="flex items-center justify-between rounded border border-stone bg-white/40 px-4 py-2"
              >
                <span className="font-medium">
                  {skill.name}
                  {skill.kind === "funny" && (
                    <span className="ml-2 text-xs text-muted">funny</span>
                  )}
                </span>
                {canWrite && (
                  <button
                    onClick={() => remove.mutate(skill.id)}
                    disabled={remove.isPending}
                    className="text-sm text-muted hover:text-ink hover:underline disabled:opacity-50"
                  >
                    Delete
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {canWrite && (
          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (newName.trim()) create.mutate();
            }}
          >
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New skill name"
              aria-label="New skill name"
              className="flex-1 rounded border border-stone px-3 py-2"
            />
            <button
              type="submit"
              disabled={create.isPending || !newName.trim()}
              className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
            >
              Add skill
            </button>
          </form>
        )}
        <ErrorMessage error={create.error ?? remove.error} />
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Category → ability</h2>
        {categories.data.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No categories yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {categories.data.map((category) => (
              <li
                key={category.id}
                className="flex items-center justify-between rounded border border-stone bg-white/40 px-4 py-2"
              >
                <span>{category.name}</span>
                <select
                  aria-label={`Ability for ${category.name}`}
                  value={category.ability}
                  disabled={!canWrite || map.isPending}
                  onChange={(e) =>
                    map.mutate({
                      categoryId: category.id,
                      ability: e.target.value as Ability,
                    })
                  }
                  className="rounded border border-stone px-2 py-1 text-sm"
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
        )}
        <ErrorMessage error={map.error} />
      </section>
    </main>
  );
}
