import { api } from "./client";
import type { BulkResult } from "./adminSkills";

export type LootBoxType =
  | "adventurer"
  | "boss"
  | "brute_force"
  | "cartographer"
  | "interrogator"
  | "party"
  | "pathfinder"
  | "purist"
  | "saboteur"
  | "specialist";

export type LootRarity =
  | "bronze"
  | "silver"
  | "gold"
  | "platinum"
  | "legendary"
  | "celestial";

export interface AdminAchievement {
  id: string;
  code: string;
  name: string;
  description: string;
  earned_by: string;
  display_order: number;
  secret: boolean;
  /** False when no trigger is registered for this code: the achievement is
   *  inert and will never fire (spec 030). */
  has_trigger: boolean;
  /** True while the description is still the seeded placeholder. */
  needs_copy: boolean;
  held_by: number;
  /** The reward. On the model since spec 038, editable since 058. */
  loot_box_type: LootBoxType | null;
  loot_rarity: LootRarity | null;
  no_loot_line: string | null;
  /** The secret theme this hands over (spec 058 §5). */
  unlocks_theme: string | null;
}

export interface TriggerCodes {
  registered: string[];
  /** Registered triggers with no achievement row — the suggestion list. */
  unused: string[];
  /** Trigger families, whose codes depend on data rather than being fixed. */
  families: string[];
}

export const listAchievements = () => api.get<AdminAchievement[]>("/admin/achievements");

export const listTriggerCodes = () => api.get<TriggerCodes>("/admin/achievements/triggers");

export const createAchievement = (input: {
  code: string;
  name: string;
  earned_by?: string;
  description?: string;
  display_order?: number;
  secret?: boolean;
  loot_box_type?: LootBoxType | null;
  loot_rarity?: LootRarity | null;
  no_loot_line?: string | null;
  unlocks_theme?: string | null;
}) => api.post<AdminAchievement>("/admin/achievements", input);

export interface AchievementUpdate {
  name?: string;
  description?: string;
  earned_by?: string;
  display_order?: number;
  secret?: boolean;
  loot_box_type?: LootBoxType | null;
  loot_rarity?: LootRarity | null;
  no_loot_line?: string | null;
  unlocks_theme?: string | null;
  /** Null in a PATCH means "not sent", so clearing needs its own flag. */
  clear_loot?: boolean;
  clear_theme?: boolean;
}

export const updateAchievement = (id: string, input: AchievementUpdate) =>
  api.patch<AdminAchievement>(`/admin/achievements/${id}`, input);

export const deleteAchievement = (id: string) =>
  api.delete<{ message: string }>(`/admin/achievements/${id}`);

export const bulkAchievements = (ids: string[], action: string, value: unknown = null) =>
  api.post<BulkResult>("/admin/achievements/bulk", { ids, action, value });
