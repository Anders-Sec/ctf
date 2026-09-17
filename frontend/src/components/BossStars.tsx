import type { BossStar, BossTier } from "../api/scoreboard";

/**
 * A run of coloured pips, one per boss felled (spec 059 §3).
 *
 * Six colours side by side is exactly where "colour is never the only carrier"
 * earns its keep, so the run carries **a text total and a per-tier breakdown in
 * its accessible label**, and each pip names its boss on hover. A sighted reader
 * gets the colour; everybody gets the count and the tiers.
 *
 * The tokens are theme-invariant by design (spec 048) — a City Boss is the same
 * colour in Parchment as in Mr. Anderson, because the tier is a fact about the
 * dungeon rather than a decision about the page.
 */

const TIER_COLOUR: Record<BossTier, string> = {
  neighborhood: "bg-boss-neighborhood",
  borough: "bg-boss-borough",
  city: "bg-boss-city",
  province: "bg-boss-province",
  country: "bg-boss-country",
  floor: "bg-boss-floor",
};

/** Ascending, so the label reads biggest-fight-first like the pips do. */
const TIER_ORDER: BossTier[] = [
  "floor",
  "country",
  "province",
  "city",
  "borough",
  "neighborhood",
];

export function starLabel(stars: BossStar[]): string {
  if (stars.length === 0) return "No bosses felled";

  const byTier = TIER_ORDER.filter((tier) => stars.some((star) => star.tier === tier)).map(
    (tier) => {
      const count = stars.filter((star) => star.tier === tier).length;
      return `${count} ${tier}`;
    },
  );
  return `${stars.length} ${stars.length === 1 ? "boss" : "bosses"} felled: ${byTier.join(", ")}`;
}

export default function BossStars({
  stars,
  size = "sm",
}: {
  stars: BossStar[];
  size?: "sm" | "lg";
}) {
  if (stars.length === 0) {
    // An empty run rather than a zero: a dash beside a name reads as a column
    // that failed to load.
    return <span className="text-xs text-content-faint">—</span>;
  }

  const pip = size === "lg" ? "h-3 w-3" : "h-2 w-2";

  return (
    <span className="inline-flex flex-wrap items-center gap-0.5" role="img" aria-label={starLabel(stars)}>
      {stars.map((star) => (
        <span
          key={star.slug}
          // The slug is the key as well as the identity — one pip per boss is
          // the whole point of keying stars on it.
          title={`${star.title} · ${star.tier}`}
          className={`inline-block rounded-full ${pip} ${TIER_COLOUR[star.tier]}`}
        />
      ))}
      {/* The count in text, next to the colour rather than instead of it. */}
      <span className="ml-1 text-xs text-content-muted tabular-nums">{stars.length}</span>
    </span>
  );
}

/** The panel's version: pips grouped and named, since there is room for it. */
export function BossStarBreakdown({ stars }: { stars: BossStar[] }) {
  if (stars.length === 0) {
    return <p className="text-sm text-content-muted">No bosses felled yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-1">
      {TIER_ORDER.filter((tier) => stars.some((star) => star.tier === tier)).map((tier) => {
        const held = stars.filter((star) => star.tier === tier);
        return (
          <li key={tier} className="flex items-baseline gap-2 text-sm">
            <span
              aria-hidden
              className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${TIER_COLOUR[tier]}`}
            />
            <span className="shrink-0 capitalize text-content-muted">{tier}</span>
            <span className="min-w-0">{held.map((star) => star.title).join(", ")}</span>
          </li>
        );
      })}
    </ul>
  );
}
