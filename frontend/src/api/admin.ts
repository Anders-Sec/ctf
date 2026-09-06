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
}

export interface UserListResponse {
  total: number;
  users: AdminUser[];
}

export const listUsers = (params: { status?: UserStatus; search?: string } = {}) => {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.search) query.set("search", params.search);
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
