/**
 * The class rarity ladder, as text colour (spec 024's ladder, 048's tokens).
 *
 * Theme-invariant on purpose, like the loot and boss ladders: a Mythic class is
 * the same colour in every theme, because the rarity is a fact about the class
 * rather than a decision about the page.
 *
 * Every use pairs it with the rarity's **name**, never colour alone. Indexed by
 * a plain string so an unrecognised value from an older payload falls back
 * rather than throwing.
 */
export const RARITY_TEXT: Record<string, string> = {
  common: "text-rarity-common",
  uncommon: "text-rarity-uncommon",
  rare: "text-rarity-rare",
  legendary: "text-rarity-legendary",
  mythic: "text-rarity-mythic",
};
