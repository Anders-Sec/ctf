import { api } from "./client";

export type SkillKind = "useful" | "funny";

export interface Skill {
  id: string;
  name: string;
  display_order: number;
  description: string | null;
  kind: SkillKind;
  /** Sorts the challenge editor's picker; it does not restrict what may carry it. */
  category_id: string | null;
  /** Challenges feeding this skill (spec 058). Zero is XP that lands nowhere. */
  challenge_count: number;
}

export type Ability = "str" | "dex" | "con" | "int" | "wis" | "cha";

export interface AdminCategory {
  id: string;
  name: string;
  slug: string;
  display_order: number;
  /** Required: an unmapped category drops its XP out of the stat block. */
  ability: Ability;
}

export interface SkillInput {
  name?: string;
  display_order?: number;
  description?: string | null;
  kind?: SkillKind;
  category_id?: string | null;
}

export const listSkills = () => api.get<Skill[]>("/admin/skills");

export const createSkill = (input: SkillInput & { name: string }) =>
  api.post<Skill>("/admin/skills", input);

export const updateSkill = (skillId: string, input: SkillInput) =>
  api.patch<Skill>(`/admin/skills/${skillId}`, input);

export const deleteSkill = (skillId: string) =>
  api.delete<{ message: string }>(`/admin/skills/${skillId}`);

export const listCategories = () => api.get<AdminCategory[]>("/admin/categories");

export const setCategoryAbility = (categoryId: string, ability: Ability) =>
  api.patch<AdminCategory>(`/admin/categories/${categoryId}/ability`, { ability });

export const getChallengeSkills = (challengeId: string) =>
  api.get<string[]>(`/admin/challenges/${challengeId}/skills`);

export const setChallengeSkills = (challengeId: string, skillIds: string[]) =>
  api.put<string[]>(`/admin/challenges/${challengeId}/skills`, {
    skill_ids: skillIds,
  });

/** One action over a selection, with per-item results (spec 058 §4). */
export interface BulkResult {
  changed: number;
  /** id → why it was refused. */
  refused: Record<string, string>;
}

export const bulkSkills = (ids: string[], action: string, value: unknown = null) =>
  api.post<BulkResult>("/admin/skills/bulk", { ids, action, value });
