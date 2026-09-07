import { api } from "./client";

export interface AdminHint {
  id: string;
  title: string;
  body: string;
  cost: number;
  display_order: number;
  prerequisite_hint_id: string | null;
  available_after: string | null;
}

export const listHints = (challengeId: string) =>
  api.get<AdminHint[]>(`/admin/challenges/${challengeId}/hints`);

export const createHint = (
  challengeId: string,
  input: { title: string; body: string; cost: number; display_order?: number },
) => api.post<AdminHint>(`/admin/challenges/${challengeId}/hints`, input);

export const updateHint = (
  challengeId: string,
  hintId: string,
  input: {
    title?: string;
    body?: string;
    cost?: number;
    display_order?: number;
  },
) =>
  api.patch<AdminHint>(
    `/admin/challenges/${challengeId}/hints/${hintId}`,
    input,
  );

export const deleteHint = (challengeId: string, hintId: string) =>
  api.delete<void>(`/admin/challenges/${challengeId}/hints/${hintId}`);
