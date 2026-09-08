import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  getCharacter,
  getClasses,
  getMyCharacter,
  setMyClass,
  type AbilityScore,
  type CharacterSheet,
  type PublicCharacter,
  type SkillRow,
} from "../api/character";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * The character sheet (specs 015, 016, 018). Your level and XP bar, a D&D stat
 * block of ability scores, your skills, and your class.
 *
 * Abilities show a score but never their progress, and skills show a level but
 * never their XP — both deliberate (spec 018). Another player's sheet at
 * /character/:userId shows the same, minus the class picker.
 */
export default function CharacterSheetPage() {
  const { userId } = useParams<{ userId?: string }>();
  const { me } = useSession();
  const isSelf = !userId || userId === me?.user.id;

  const own = useQuery({
    queryKey: ["character", "me"],
    queryFn: getMyCharacter,
    enabled: isSelf,
  });
  const other = useQuery({
    queryKey: ["character", userId],
    queryFn: () => getCharacter(userId as string),
    enabled: !isSelf,
  });

  const query = isSelf ? own : other;
  if (query.isPending) return <Spinner label="Unrolling the character sheet…" />;
  if (query.isError) return <ErrorMessage error={query.error} />;

  return isSelf ? (
    <OwnSheet sheet={own.data as CharacterSheet} />
  ) : (
    <PublicSheet sheet={other.data as PublicCharacter} />
  );
}

function OwnSheet({ sheet }: { sheet: CharacterSheet }) {
  return (
    <main className="mx-auto max-w-2xl p-6">
      <Header
        userId={sheet.user_id}
        displayName={sheet.display_name}
        hasAvatar={sheet.has_avatar}
        level={sheet.level}
        className={sheet.character_class?.name ?? null}
        rank={sheet.rank}
      />

      <ClassSection sheet={sheet} />

      <section className="mt-6 rounded border border-stone bg-white/40 p-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Level {sheet.level}</h2>
          <span className="text-sm text-muted tabular-nums">{sheet.total_xp} XP total</span>
        </div>
        <XpBar into={sheet.xp_into_level} toNext={sheet.xp_to_next} />
        <p className="mt-1 text-sm text-muted">
          {sheet.xp_to_next > 0
            ? `${sheet.xp_to_next} XP to level ${sheet.level + 1}`
            : "Top of the curve for now"}
        </p>
      </section>

      <StatBlock abilities={sheet.abilities} />
      <SkillTable skills={sheet.skills} />
    </main>
  );
}

function ClassSection({ sheet }: { sheet: CharacterSheet }) {
  const queryClient = useQueryClient();
  const roster = useQuery({
    queryKey: ["character", "classes"],
    queryFn: getClasses,
    enabled: sheet.class_unlocked,
  });
  const choose = useMutation({
    mutationFn: (classId: string | null) => setMyClass(classId),
    onSuccess: (updated) => queryClient.setQueryData(["character", "me"], updated),
  });

  return (
    <section className="mt-6 rounded border border-stone bg-white/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Class</h2>
        {sheet.class_unlocked ? (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">Your calling</span>
            <select
              aria-label="Class"
              value={sheet.character_class?.id ?? ""}
              disabled={choose.isPending || roster.isPending}
              onChange={(e) => choose.mutate(e.target.value || null)}
              className="rounded border border-stone px-2 py-1 text-sm"
            >
              <option value="">Classless</option>
              {(roster.data ?? []).map((klass) => (
                <option key={klass.id} value={klass.id}>
                  {klass.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="text-sm text-muted">
            Reach level {sheet.class_unlock_level} to choose a class
          </span>
        )}
      </div>

      <ErrorMessage error={choose.error} />
    </section>
  );
}

function PublicSheet({ sheet }: { sheet: PublicCharacter }) {
  return (
    <main className="mx-auto max-w-2xl p-6">
      <Header
        userId={sheet.user_id}
        displayName={sheet.display_name}
        hasAvatar={sheet.has_avatar}
        level={sheet.level}
        className={sheet.character_class?.name ?? null}
        rank={null}
      />

      <StatBlock abilities={sheet.abilities} />
      <SkillTable skills={sheet.skills} />
    </main>
  );
}

const ABILITY_LABEL: Record<string, string> = {
  str: "Strength",
  dex: "Dexterity",
  con: "Constitution",
  int: "Intelligence",
  wis: "Wisdom",
  cha: "Charisma",
};

/** The D&D stat block. Scores only — how close the next point is stays hidden,
 *  so abilities tick up quietly (spec 018). */
function StatBlock({ abilities }: { abilities: AbilityScore[] }) {
  if (abilities.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Abilities</h2>
      <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {abilities.map((a) => (
          <li
            key={a.ability}
            className="rounded border border-stone bg-white/40 p-3 text-center"
          >
            <div className="text-xs uppercase tracking-wide text-muted">
              {ABILITY_LABEL[a.ability] ?? a.ability}
            </div>
            <div className="mt-1 text-3xl font-semibold tabular-nums">{a.score}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Name and level, nothing else. Undiscovered skills arrive already redacted
 *  from the server and render blurred, so the shape of what is left to find is
 *  visible without the content. */
function SkillTable({ skills }: { skills: SkillRow[] }) {
  const [query, setQuery] = useState("");
  const [hideFunny, setHideFunny] = useState(false);

  const rows = skills
    .filter((s) => (hideFunny ? s.kind !== "funny" : true))
    // A placeholder has nothing to match, so search only finds discovered ones.
    .filter((s) => (query ? s.discovered && s.name.toLowerCase().includes(query.toLowerCase()) : true));

  const found = skills.filter((s) => s.discovered).length;

  if (skills.length === 0) return null;

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">Skills</h2>
        <span className="text-sm text-muted">
          {found} of {skills.length} discovered
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search skills"
          aria-label="Search skills"
          className="flex-1 rounded border border-stone px-3 py-1.5 text-sm"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={hideFunny}
            onChange={(e) => setHideFunny(e.target.checked)}
          />
          Hide funny skills
        </label>
      </div>

      <ul className="mt-3 divide-y divide-stone rounded border border-stone bg-white/40">
        {rows.map((skill) => (
          <li key={skill.skill_id} className="flex items-center justify-between px-4 py-2">
            <span
              className={skill.discovered ? "" : "select-none blur-sm"}
              aria-label={skill.discovered ? undefined : "Undiscovered skill"}
            >
              {skill.name}
              {skill.kind === "funny" && skill.discovered && (
                <span className="ml-2 text-xs text-muted">funny</span>
              )}
            </span>
            <span className="text-sm text-muted tabular-nums">
              {skill.discovered ? `Level ${skill.level}` : "—"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Header({
  userId,
  displayName,
  hasAvatar,
  level,
  className,
  rank,
}: {
  userId: string;
  displayName: string;
  hasAvatar: boolean;
  level: number;
  className: string | null;
  rank: number | null;
}) {
  return (
    <header className="flex items-center gap-4">
      <Avatar userId={userId} displayName={displayName} hasAvatar={hasAvatar} size={56} />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{displayName}</h1>
        <p className="text-sm text-muted">
          Level {level} {className ?? "Classless"} adventurer
          {rank !== null ? ` · rank #${rank}` : ""}
        </p>
      </div>
    </header>
  );
}

function XpBar({ into, toNext }: { into: number; toNext: number }) {
  const span = into + toNext;
  // A level whose next threshold is unknown (top of the curve) reads as full.
  const pct = span > 0 ? Math.round((into / span) * 100) : 100;
  return (
    <div
      className="mt-3 h-2 w-full overflow-hidden rounded-full bg-stone/40"
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="h-full rounded-full bg-ink" style={{ width: `${pct}%` }} />
    </div>
  );
}
