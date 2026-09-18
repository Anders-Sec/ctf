import type { AbilityScore, SkillRow } from "../../api/character";
import { FilteredList, SheetPanel } from "./SheetPanel";

/**
 * Abilities and the skills they are made of (spec 060 §3).
 *
 * The left column, as on a printed 5e sheet — and for the same reason: these are
 * the numbers that describe the character rather than the things they have
 * collected.
 */

const ABILITY_LABEL: Record<string, string> = {
  str: "STR",
  dex: "DEX",
  con: "CON",
  int: "INT",
  wis: "WIS",
  cha: "CHA",
};

const ABILITY_NAME: Record<string, string> = {
  str: "Strength",
  dex: "Dexterity",
  con: "Constitution",
  int: "Intelligence",
  wis: "Wisdom",
  cha: "Charisma",
};

export default function StatsPanel({
  abilities,
  skills,
  skillsTotal,
}: {
  abilities: AbilityScore[];
  skills: SkillRow[];
  /** Defaults to the list length. Somebody else's sheet sends only discovered
   *  rows, so it has to pass the roster size for `N of M` to be true. */
  skillsTotal?: number;
}) {
  const found = skills.filter((skill) => skill.discovered).length;
  const total = skillsTotal ?? skills.length;
  // On somebody else's sheet every row is discovered, so a Discovered filter
  // would be a control that does nothing. Derived rather than passed in: it is
  // also true for a player who has found everything on their own sheet.
  const anyUndiscovered = found < skills.length;

  return (
    <SheetPanel
      title="Stats"
      summary={`${found} of ${total} skills discovered`}
      className="h-[38rem]"
    >
      {/* Score-in-a-box, six across two rows. No progress toward the next
          point: abilities tick up quietly by design (spec 018). */}
      <ul className="mb-3 grid shrink-0 grid-cols-3 gap-2">
        {abilities.map((ability) => (
          <li
            key={ability.ability}
            title={ABILITY_NAME[ability.ability] ?? ability.ability}
            className="rounded border border-border bg-surface px-1 py-1.5 text-center"
          >
            <span className="block text-[10px] uppercase tracking-wider text-content-muted">
              {ABILITY_LABEL[ability.ability] ?? ability.ability}
            </span>
            <span className="block text-2xl font-semibold leading-tight tabular-nums">
              {ability.score}
            </span>
          </li>
        ))}
      </ul>

      <h3 className="mb-2 shrink-0 border-t border-border pt-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
        Skills
      </h3>

      <FilteredList
        items={skills}
        listLabel="Skills"
        searchLabel="Search skills"
        searchHint={
          anyUndiscovered ? "Only discovered skills can be found by name." : undefined
        }
        filters={[
          {
            id: "kind",
            label: "Any kind",
            options: [
              { value: "useful", label: "Useful" },
              { value: "funny", label: "Funny" },
            ],
          },
          ...(anyUndiscovered
            ? [
                {
                  id: "discovered",
                  label: "All skills",
                  options: [{ value: "yes", label: "Discovered only" }],
                },
              ]
            : []),
        ]}
        match={(skill, { term, values }) => {
          if (values.kind && skill.kind !== values.kind) return false;
          if (values.discovered === "yes" && !skill.discovered) return false;
          // A placeholder has nothing to match: the server sends no name for an
          // undiscovered skill, so search can only ever find discovered ones.
          if (term) return skill.discovered && skill.name.toLowerCase().includes(term);
          return true;
        }}
        rowKey={(skill) => skill.skill_id}
        empty="No skills yet. They appear as you earn XP in them."
        renderRow={(skill) => (
          <div className="flex items-center justify-between gap-2 px-1 py-1.5 text-sm">
            <span
              className={`min-w-0 truncate ${skill.discovered ? "" : "select-none blur-sm"}`}
              aria-label={skill.discovered ? undefined : "Undiscovered skill"}
            >
              {skill.name}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {skill.kind === "funny" && skill.discovered && (
                <span className="text-[10px] uppercase tracking-wide text-content-faint">
                  funny
                </span>
              )}
              <span className="text-xs text-content-muted tabular-nums">
                {skill.discovered ? `Lv ${skill.level}` : "—"}
              </span>
            </span>
          </div>
        )}
      />
    </SheetPanel>
  );
}
