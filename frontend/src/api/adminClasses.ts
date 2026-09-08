import { api } from "./client";

export interface CharacterClass {
  id: string;
  name: string;
  display_order: number;
  description: string | null;
  affinity_skill_id: string | null;
}

export const listClasses = () => api.get<CharacterClass[]>("/admin/classes");

export const createClass = (input: {
  name: string;
  display_order?: number;
  description?: string | null;
  affinity_skill_id?: string | null;
}) => api.post<CharacterClass>("/admin/classes", input);

export const updateClass = (
  classId: string,
  input: {
    name?: string;
    display_order?: number;
    description?: string | null;
    affinity_skill_id?: string | null;
  },
) => api.patch<CharacterClass>(`/admin/classes/${classId}`, input);

export const deleteClass = (classId: string) =>
  api.delete<{ message: string }>(`/admin/classes/${classId}`);
