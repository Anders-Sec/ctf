import type { PublicCharacter } from "../../api/character";
import Avatar from "../Avatar";
import { RARITY_TEXT } from "../classRarity";
import { Fact } from "./SheetPanel";

/**
 * Somebody else's identity block (spec 061 §2).
 *
 * The same block as the own sheet's minus one thing — **the XP bar and the
 * total** — which is the only structural difference between the two sheets'
 * headers. Everything a player shows the room stays: name, avatar, worn title,
 * class, level, rank and party.
 *
 * The class is static text here. Somebody else's calling is not yours to change,
 * so there is no dialog behind it.
 */
export default function PublicPlayerInfo({
  sheet,
  onOpenParty,
}: {
  sheet: PublicCharacter;
  /** Opens 059's party panel. Not `/party` — that is the *viewer's* own party. */
  onOpenParty: (teamId: string) => void;
}) {
  return (
    <section className="rounded-lg border border-border-strong bg-surface-raised p-4">
      <div className="flex flex-wrap items-start gap-4">
        <Avatar
          userId={sheet.user_id}
          displayName={sheet.display_name}
          hasAvatar={sheet.has_avatar}
          size={56}
        />

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold tracking-tight">
            {sheet.display_name}
          </h1>
          {sheet.equipped_title && (
            <p className="truncate text-sm italic text-content-muted">
              {sheet.equipped_title}
            </p>
          )}
        </div>

        <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Fact label="Class">
            <span
              className={`font-medium ${
                sheet.character_class
                  ? (RARITY_TEXT[sheet.character_class.rarity] ?? "")
                  : "text-content-muted"
              }`}
            >
              {sheet.character_class?.name ?? "Classless"}
            </span>
          </Fact>
          <Fact label="Level">
            <span className="font-medium tabular-nums">{sheet.level}</span>
          </Fact>
          <Fact label="Rank">
            <span className="font-medium tabular-nums">
              {/* Null for anybody the board does not hold — staff are excluded
                  from it by design, and they genuinely have no rank. */}
              {sheet.rank === null ? "unranked" : `#${sheet.rank}`}
            </span>
          </Fact>
          <Fact label="Party">
            {sheet.party ? (
              <button
                type="button"
                onClick={() => onOpenParty(sheet.party!.id)}
                className="font-medium hover:underline"
              >
                {sheet.party.name}
              </button>
            ) : (
              <span className="text-content-muted">none</span>
            )}
          </Fact>
        </dl>
      </div>
    </section>
  );
}
