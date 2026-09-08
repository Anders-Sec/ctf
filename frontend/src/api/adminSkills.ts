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

export const listSkills = () => api.get<Skill[]>("/admin/skills");

export const createSkill = (input: {
  name: string;
  display_order?: number;
  description?: string | null;
  kind?: SkillKind;
  category_id?: string | null;
}) => api.post<Skill>("/admin/skills", input);

export const updateSkill = (
  skillId: string,
  input: {
    name?: string;
    display_order?: number;
    description?: string | null;
    kind?: SkillKind;
    category_id?: string | null;
  },
) => api.patch<Skill>(`/admin/skills/${skillId}`, input);

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
