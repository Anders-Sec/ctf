import { api } from "./client";

export interface Skill {
  id: string;
  name: string;
  display_order: number;
  description: string | null;
}

export interface AdminCategory {
  id: string;
  name: string;
  slug: string;
  display_order: number;
  skill_id: string | null;
}

export const listSkills = () => api.get<Skill[]>("/admin/skills");

export const createSkill = (input: {
  name: string;
  display_order?: number;
  description?: string | null;
}) => api.post<Skill>("/admin/skills", input);

export const updateSkill = (
  skillId: string,
  input: { name?: string; display_order?: number; description?: string | null },
) => api.patch<Skill>(`/admin/skills/${skillId}`, input);

export const deleteSkill = (skillId: string) =>
  api.delete<{ message: string }>(`/admin/skills/${skillId}`);

export const listCategories = () => api.get<AdminCategory[]>("/admin/categories");

export const setCategorySkill = (categoryId: string, skillId: string | null) =>
  api.patch<AdminCategory>(`/admin/categories/${categoryId}/skill`, {
    skill_id: skillId,
  });
