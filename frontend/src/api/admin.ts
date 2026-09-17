import { api } from "./client";
import type { UserRole, UserSource, UserStatus } from "./auth";

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  source: UserSource;
  role: UserRole;
  status: UserStatus;
  created_at: string;
  approved_at: string | null;
  last_login_at: string | null;
  /** Roster columns (spec 052 §2): enough to tell a real player from a
   *  dormant account without opening anything. */
  party_name: string | null;
  solve_count: number;
  xp: number;
}

export interface UserListResponse {
  total: number;
  users: AdminUser[];
}

export interface UserFilters {
  status?: UserStatus;
  source?: UserSource;
  role?: UserRole;
  search?: string;
  limit?: number;
  offset?: number;
}

export const listUsers = (params: UserFilters = {}) => {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString();
  return api.get<UserListResponse>(`/admin/users${suffix ? `?${suffix}` : ""}`);
};

/** Takes a list: approving 200 guests one at a time is not a plan. */
export const approveUsers = (userIds: string[], reason?: string) =>
  api.post<UserListResponse>("/admin/users/approve", {
    user_ids: userIds,
    reason: reason ?? null,
  });

export const disableUser = (userId: string, reason: string) =>
  api.post<AdminUser>(`/admin/users/${userId}/disable`, { reason });

/** A membership, current or ended (spec 052 §3). */
export interface PartySpell {
  team_id: string;
  team_name: string;
  role: string;
  joined_at: string;
  removed_at: string | null;
  removal_reason: string | null;
}

export interface ActivityEntry {
  challenge_id: string;
  challenge_title: string | null;
  is_correct: boolean;
  created_at: string;
}

export interface UserDetail {
  user: AdminUser;
  entra_object_id: string | null;
  approved_by_name: string | null;
  disabled_reason: string | null;
  assistant_blocked: boolean;
  level: number;
  hints_used: number;
  achievement_count: number;
  class_name: string | null;
  parties: PartySpell[];
  recent_activity: ActivityEntry[];
  /** The challenge most recently attempted without solving. */
  current_wall: string | null;
}

export const getUser = (userId: string) => api.get<UserDetail>(`/admin/users/${userId}`);

export const enableUser = (userId: string, reason: string) =>
  api.post<AdminUser>(`/admin/users/${userId}/enable`, { reason });

export const setUserRole = (userId: string, role: UserRole, reason?: string) =>
  api.post<AdminUser>(`/admin/users/${userId}/role`, { role, reason: reason ?? null });

export const setAssistantBlock = (userId: string, blocked: boolean, reason?: string) =>
  api.post<AdminUser>(`/admin/users/${userId}/assistant-block`, {
    blocked,
    reason: reason ?? null,
  });

export const resendMagicLink = (userId: string) =>
  api.post<{ message: string }>(`/admin/users/${userId}/resend-magic-link`, {});
