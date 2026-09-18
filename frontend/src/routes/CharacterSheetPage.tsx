import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  getCharacter,
  getMyCharacter,
  type CharacterSheet,
  type PublicCharacter,
} from "../api/character";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import PartyPanel from "../components/PartyPanel";
import Spinner from "../components/Spinner";
import AchievementsPanel from "../components/sheet/AchievementsPanel";
import FeatsPanel from "../components/sheet/FeatsPanel";
import LootPanel from "../components/sheet/LootPanel";
import PlayerInfo from "../components/sheet/PlayerInfo";
import PublicPlayerInfo from "../components/sheet/PublicPlayerInfo";
import StatsPanel from "../components/sheet/StatsPanel";
import TrophyCasePanel from "../components/sheet/TrophyCasePanel";

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
 * **Somebody else's sheet** at `/character/:userId` is the same grid panel for
 * panel (spec 061), minus the XP bar, minus loot, minus the class dialog — what
 * a player shows the room, and nothing that is nobody else's business.
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

/**
 * Somebody else's sheet (spec 061).
 *
 * The same four blocks as the own sheet, at the same heights and breakpoints, so
 * the two read as one artifact rather than two designs. Loot's slot carries
 * Feats instead: a stranger's inventory is not a thing to browse.
 */
function PublicSheet({ sheet }: { sheet: PublicCharacter }) {
  const [openParty, setOpenParty] = useState<string | null>(null);

  return (
    <main className="mx-auto max-w-5xl p-4 sm:p-6">
      <PublicPlayerInfo sheet={sheet} onOpenParty={setOpenParty} />

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {/* Every row is discovered, so the panel drops its Discovered filter on
            its own and nothing is blurred. `skills_total` is what keeps
            "N of M discovered" true with the rest never sent. */}
        <StatsPanel
          abilities={sheet.abilities}
          skills={sheet.skills}
          skillsTotal={sheet.skills_total}
        />
        <div className="flex flex-col gap-4">
          <TrophyCasePanel userId={sheet.user_id} />
          <FeatsPanel sheet={sheet} />
        </div>
      </div>

      {openParty && <PartyPanel teamId={openParty} onClose={() => setOpenParty(null)} />}
    </main>
  );
}
