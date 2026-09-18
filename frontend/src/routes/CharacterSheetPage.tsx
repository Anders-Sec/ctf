import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  getCharacter,
  getMyCharacter,
  type AbilityScore,
  type CharacterSheet,
  type PublicCharacter,
  type SkillRow,
} from "../api/character";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import AchievementsPanel from "../components/sheet/AchievementsPanel";
import LootPanel from "../components/sheet/LootPanel";
import PlayerInfo from "../components/sheet/PlayerInfo";
import StatsPanel from "../components/sheet/StatsPanel";

/**
 * The character sheet (specs 015, 016, 018; laid out by 060).
 *
 * **Own sheet:** identity across the top, stats down the left as on a printed 5e
 * sheet, and the things the player has collected stacked on the right. Every
 * panel is a fixed height, which is what makes the page read as a sheet rather
 * than a feed — nothing moves when a box is opened or a skill is discovered, and
 * the layout is the same for a level-2 player and a level-15 one.
 *
 * Abilities show a score but never their progress, and skills show a level but
 * never their XP — both deliberate (spec 018).
 *
 * **Somebody else's sheet** at `/character/:userId` is untouched by 060 and is
 * its own pass.
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
    // Wider than the old 2xl column because the whole point is two columns of
    // content rather than one of everything.
    <main className="mx-auto max-w-5xl p-4 sm:p-6">
      <PlayerInfo sheet={sheet} />

      {/* One column on a phone, in reading order — the left column lands before
          the right, so it matches what the eye does on the wide layout
          (spec 060 §2.2). */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <StatsPanel abilities={sheet.abilities} skills={sheet.skills} />
        <div className="flex flex-col gap-4">
          <AchievementsPanel />
          <LootPanel />
        </div>
      </div>
    </main>
  );
}

/** Somebody else's sheet. Spec 060 covers the own sheet only; this is next. */
function PublicSheet({ sheet }: { sheet: PublicCharacter }) {
  return (
    <main className="mx-auto max-w-2xl p-6">
      <Header
        userId={sheet.user_id}
        displayName={sheet.display_name}
        hasAvatar={sheet.has_avatar}
        level={sheet.level}
        className={sheet.character_class?.name ?? null}
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
            className="rounded border border-border bg-surface-raised p-3 text-center"
          >
            <div className="text-xs uppercase tracking-wide text-content-muted">
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
    .filter((s) =>
      query ? s.discovered && s.name.toLowerCase().includes(query.toLowerCase()) : true,
    );

  const found = skills.filter((s) => s.discovered).length;

  if (skills.length === 0) return null;

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">Skills</h2>
        <span className="text-sm text-content-muted">
          {found} of {skills.length} discovered
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search skills"
          aria-label="Search skills"
          className="flex-1 rounded border border-border px-3 py-1.5 text-sm"
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

      <ul className="mt-3 divide-y divide-stone rounded border border-border bg-surface-raised">
        {rows.map((skill) => (
          <li key={skill.skill_id} className="flex items-center justify-between px-4 py-2">
            <span
              className={skill.discovered ? "" : "select-none blur-sm"}
              aria-label={skill.discovered ? undefined : "Undiscovered skill"}
            >
              {skill.name}
              {skill.kind === "funny" && skill.discovered && (
                <span className="ml-2 text-xs text-content-muted">funny</span>
              )}
            </span>
            <span className="text-sm text-content-muted tabular-nums">
              {skill.discovered ? `Level ${skill.level}` : "—"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Unchanged from before spec 060 — the public sheet is its own pass. */
function Header({
  userId,
  displayName,
  hasAvatar,
  level,
  className,
}: {
  userId: string;
  displayName: string;
  hasAvatar: boolean;
  level: number;
  className: string | null;
}) {
  return (
    <header className="flex items-center gap-4">
      <Avatar userId={userId} displayName={displayName} hasAvatar={hasAvatar} size={56} />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{displayName}</h1>
        <p className="text-sm text-content-muted">
          Level {level} {className ?? "Classless"} adventurer
        </p>
      </div>
    </header>
  );
}
