import type { Rarity } from "../api/character";

/**
 * A class's rarity (spec 024).
 *
 * Colour is never the only signal — the rarity word is always rendered, so this
 * reads correctly in greyscale and to a screen reader. Rarity is presentation:
 * it gates nothing and scores nothing.
 */
const TONE: Record<Rarity, string> = {
  common: "border-rarity-common/40 text-rarity-common",
  uncommon: "border-rarity-uncommon/50 text-rarity-uncommon",
  rare: "border-rarity-rare/50 text-rarity-rare",
  legendary: "border-rarity-legendary/60 text-rarity-legendary",
  mythic: "border-rarity-mythic/60 text-rarity-mythic",
};

export default function RarityBadge({ rarity }: { rarity: Rarity }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${TONE[rarity]}`}
    >
      {rarity}
    </span>
  );
}
