import { api } from "./client";

/** The six-tier ladder. Same six colours the boss stars use (specs 031, 038). */
export type LootRarity =
  | "bronze"
  | "silver"
  | "gold"
  | "platinum"
  | "legendary"
  | "celestial";

export const LOOT_RARITY_CLASS: Record<LootRarity, string> = {
  bronze: "text-loot-bronze",
  silver: "text-loot-silver",
  gold: "text-loot-gold",
  platinum: "text-loot-platinum",
  legendary: "text-loot-legendary",
  celestial: "text-loot-celestial",
};

export const LOOT_RARITY_BORDER: Record<LootRarity, string> = {
  bronze: "border-loot-bronze/50",
  silver: "border-loot-silver/50",
  gold: "border-loot-gold/60",
  platinum: "border-loot-platinum/60",
  legendary: "border-loot-legendary/60",
  celestial: "border-loot-celestial/70",
};

/** Titles are cosmetic; the tier is a statement about how good one sounds. */
export const boxLabel = (boxType: string) =>
  boxType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export interface LootBox {
  id: string;
  box_type: string;
  rarity: LootRarity;
  achievement_name: string;
  created_at: string;
}

export interface HeldTitle {
  item_id: string;
  title: string;
  rarity: LootRarity;
  box_type: string;
  generated: boolean;
  equipped: boolean;
}

export interface Opened {
  box_id: string;
  title: string;
  rarity: LootRarity;
  box_type: string;
  generated: boolean;
}

export const getBoxes = () => api.get<LootBox[]>("/loot/boxes");
export const getTitles = () => api.get<HeldTitle[]>("/loot/titles");
export const openBox = (id: string) => api.post<Opened>(`/loot/boxes/${id}/open`);
export const equipTitle = (itemId: string | null) =>
  api.put<{ message: string }>("/loot/equipped", { item_id: itemId });
