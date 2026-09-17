import { api } from "./client";
import type { Ability, BulkResult } from "./adminSkills";

export type Rarity = "common" | "uncommon" | "rare" | "legendary" | "mythic";

/** Exactly one of the two, matching the model's CHECK (spec 024). */
export interface ClassPreference {
  ability: Ability | null;
  skill_id: string | null;
}

export interface ClassRequirement {
  skill_id: string;
  min_level: number;
}

export interface CharacterClass {
  id: string;
  name: string;
  display_order: number;
  description: string | null;
  /** Presentation only — never read by a gate, a score or an ordering. */
  rarity: Rarity;
  preferences: ClassPreference[];
  requirements: ClassRequirement[];
  preference_count: number;
  requirement_count: number;
  /** Why a delete can be refused: the FK is SET NULL, so it would silently
   *  return players to Classless. */
  wearers: number;
}

export interface ClassInput {
  name?: string;
  display_order?: number;
  description?: string | null;
  rarity?: Rarity;
}

export const listClasses = () => api.get<CharacterClass[]>("/admin/classes");

export const createClass = (input: ClassInput & { name: string }) =>
  api.post<CharacterClass>("/admin/classes", input);

export const updateClass = (classId: string, input: ClassInput) =>
  api.patch<CharacterClass>(`/admin/classes/${classId}`, input);

export const deleteClass = (classId: string) =>
  api.delete<{ message: string }>(`/admin/classes/${classId}`);

/** Replaces the whole set, like `PUT /admin/challenges/{id}/skills` (spec 058 §4). */
export const setClassPreferences = (classId: string, preferences: ClassPreference[]) =>
  api.put<CharacterClass>(`/admin/classes/${classId}/preferences`, { preferences });

export const setClassRequirements = (classId: string, requirements: ClassRequirement[]) =>
  api.put<CharacterClass>(`/admin/classes/${classId}/requirements`, { requirements });

export const bulkClasses = (ids: string[], action: string, value: unknown = null) =>
  api.post<BulkResult>("/admin/classes/bulk", { ids, action, value });
