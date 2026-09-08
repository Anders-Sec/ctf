import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  getCharacter,
  getClasses,
  getMyCharacter,
  setMyClass,
  type CharacterSheet,
  type PublicCharacter,
} from "../api/character";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * The character sheet (spec 015, 016). Viewed for yourself at /character —
 * overall level, skills, and your class (with the System AI's suggested-class
 * nudge) — or for another player at /character/:userId, which shows their level,
 * skills and class without the picker or the nudge.
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

      <h2 className="mt-8 text-lg font-semibold">Skills</h2>
      {sheet.skills.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          No skills defined yet — an organizer maps categories to skills.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {sheet.skills.map((skill) => (
            <li key={skill.skill_id} className="rounded border border-stone bg-white/40 p-4">
              <div className="flex items-baseline justify-between">
                <span className="font-medium">{skill.name}</span>
                <span className="text-sm text-muted tabular-nums">
                  Level {skill.level} · {skill.xp} XP
                </span>
              </div>
              <XpBar into={skill.xp_into_level} toNext={skill.xp_to_next} />
            </li>
          ))}
        </ul>
      )}
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

      {sheet.suggested_class && (
        <SystemAiNudge text={sheet.suggested_class.narration} />
      )}
      <ErrorMessage error={choose.error} />
    </section>
  );
}

/** The System AI's voiced nudge (spec 016), attributed to it like the assistant. */
function SystemAiNudge({ text }: { text: string }) {
  return (
    <aside
      aria-label="System AI"
      className="mt-3 rounded border border-stone bg-parchment px-3 py-2"
    >
      <p className="text-xs font-semibold text-muted">System AI</p>
      <p className="mt-0.5 text-sm">{text}</p>
    </aside>
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

      <h2 className="mt-8 text-lg font-semibold">Skills</h2>
      {sheet.skills.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No skills to show yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {sheet.skills.map((skill) => (
            <li
              key={skill.skill_id}
              className="flex items-baseline justify-between rounded border border-stone bg-white/40 px-4 py-3"
            >
              <span className="font-medium">{skill.name}</span>
              <span className="text-sm text-muted">Level {skill.level}</span>
            </li>
          ))}
        </ul>
      )}
    </main>
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
