import { useMemo, useState } from "react";

import type { Skill } from "../api/adminSkills";

/**
 * Choosing a challenge's skills (spec 018).
 *
 * Every skill is selectable — a skill's category only decides where it *sorts*,
 * not what may carry it. So the list is ordered to put the likely ones first:
 * this category's useful skills, then its funny ones, then everything else. With
 * 73 skills that ordering does most of the work, and search covers the rest.
 *
 * Nothing is pre-selected: what a challenge teaches is a judgement, and a
 * pre-ticked list would get accepted unread.
 */
export default function SkillPicker({
  skills,
  categoryId,
  selected,
  disabled,
  onChange,
}: {
  skills: Skill[];
  categoryId: string | null;
  selected: string[];
  disabled?: boolean;
  onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");

  const ordered = useMemo(() => {
    const rank = (skill: Skill) => {
      if (skill.category_id && skill.category_id === categoryId) {
        return skill.kind === "useful" ? 0 : 1;
      }
      return skill.kind === "useful" ? 2 : 3;
    };
    return [...skills].sort(
      (a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name),
    );
  }, [skills, categoryId]);

  const shown = query
    ? ordered.filter((s) => s.name.toLowerCase().includes(query.toLowerCase()))
    : ordered;

  const chosen = new Set(selected);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next]);
  };

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">Skills</span>
        <span className="text-xs text-muted">{selected.length} selected</span>
      </div>
      <p className="mt-1 text-xs text-muted">
        Solving this feeds every skill below in full — attaching several costs the
        player nothing.
      </p>

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search all skills"
        aria-label="Search skills"
        disabled={disabled}
        className="mt-2 w-full rounded border border-stone px-3 py-1.5 text-sm"
      />

      <ul className="mt-2 max-h-56 overflow-y-auto rounded border border-stone bg-white/60">
        {shown.length === 0 && (
          <li className="px-3 py-2 text-sm text-muted">No skills match.</li>
        )}
        {shown.map((skill) => {
          const relevant = Boolean(skill.category_id && skill.category_id === categoryId);
          return (
            <li key={skill.id}>
              <label className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-ink/5">
                <input
                  type="checkbox"
                  checked={chosen.has(skill.id)}
                  disabled={disabled}
                  onChange={() => toggle(skill.id)}
                />
                <span className={relevant ? "font-medium" : ""}>{skill.name}</span>
                {skill.kind === "funny" && (
                  <span className="text-xs text-muted">funny</span>
                )}
                {relevant && (
                  <span className="ml-auto text-xs text-muted">this category</span>
                )}
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
