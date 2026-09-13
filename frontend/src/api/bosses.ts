import { api } from "./client";

/** The six boss tiers (spec 031). Ascending; the level is what a client orders
 *  by, so the names never have to be hardcoded in a comparison. */
export type BossTier =
  | "neighborhood"
  | "borough"
  | "city"
  | "province"
  | "country"
  | "floor";

export const BOSS_TIERS: BossTier[] = [
  "neighborhood",
  "borough",
  "city",
  "province",
  "country",
  "floor",
];

export const BOSS_TIER_LABEL: Record<BossTier, string> = {
  neighborhood: "Neighborhood Boss",
  borough: "Borough Boss",
  city: "City Boss",
  province: "Province Boss",
  country: "Country Boss",
  floor: "Floor Boss",
};

/** Colour is never the only signal — the tier name is always rendered too. */
export const BOSS_TIER_CLASS: Record<BossTier, string> = {
  neighborhood: "text-boss-neighborhood",
  borough: "text-boss-borough",
  city: "text-boss-city",
  province: "text-boss-province",
  country: "text-boss-country",
  floor: "text-boss-floor",
};

export interface Star {
  challenge_id: string;
  challenge_title: string;
  zone_name: string;
  tier: BossTier;
  level: number;
}

export const getStars = () => api.get<Star[]>("/character/stars");
