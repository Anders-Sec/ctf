import { api } from "./client";

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
}

export interface TriggerCodes {
  registered: string[];
  /** Registered triggers with no achievement row — the suggestion list. */
  unused: string[];
}

export const listAchievements = () =>
  api.get<AdminAchievement[]>("/admin/achievements");

export const listTriggerCodes = () =>
  api.get<TriggerCodes>("/admin/achievements/triggers");

export const createAchievement = (input: {
  code: string;
  name: string;
  earned_by?: string;
  description?: string;
  display_order?: number;
  secret?: boolean;
}) => api.post<AdminAchievement>("/admin/achievements", input);

export const updateAchievement = (
  id: string,
  input: {
    name?: string;
    description?: string;
    earned_by?: string;
    display_order?: number;
    secret?: boolean;
  },
) => api.patch<AdminAchievement>(`/admin/achievements/${id}`, input);

export const deleteAchievement = (id: string) =>
  api.delete<{ message: string }>(`/admin/achievements/${id}`);
