import { api } from "./client";

export type InstanceStatus = "pending" | "running" | "failed" | "expired" | "destroyed";

export interface Instance {
  id: string;
  challenge_id: string;
  status: InstanceStatus;
  /** Present once running — where the player points their browser. */
  connection_url: string | null;
  expires_at: string;
  error: string | null;
  /**
   * How many *other* published challenges this container also serves (spec 046).
   * Zero for an ordinary target, which is every target that existed before it.
   */
  shared_challenge_count: number;
}

export const launchInstance = (challengeId: string) =>
  api.post<Instance>(`/challenges/${challengeId}/instance`);

export const getInstance = (challengeId: string) =>
  api.get<Instance>(`/challenges/${challengeId}/instance`);

export const destroyInstance = (challengeId: string) =>
  api.delete<void>(`/challenges/${challengeId}/instance`);

export const extendInstance = (challengeId: string) =>
  api.post<Instance>(`/challenges/${challengeId}/instance/extend`);
