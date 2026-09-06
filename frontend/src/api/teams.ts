import { api } from "./client";

export type TeamVisibility = "public" | "private";

export interface TeamListItem {
  id: string;
  name: string;
  visibility: TeamVisibility;
  member_count: number;
  max_members: number;
  has_space: boolean;
  requires_password: boolean;
}

export interface TeamMember {
  user_id: string;
  display_name: string;
  is_leader: boolean;
  has_avatar: boolean;
  joined_at: string;
}

export interface TeamDetail extends TeamListItem {
  leader_user_id: string;
  members: TeamMember[];
  created_at: string;
}

export interface JoinRequest {
  id: string;
  team_id: string;
  user_id: string;
  display_name: string;
  status: "pending" | "accepted" | "rejected" | "cancelled";
  message: string | null;
  created_at: string;
}

export const listTeams = () => api.get<TeamListItem[]>("/teams");
export const getTeam = (id: string) => api.get<TeamDetail>(`/teams/${id}`);

export const createTeam = (input: {
  name: string;
  visibility: TeamVisibility;
  join_password?: string | null;
}) => api.post<TeamDetail>("/teams", input);

export const updateTeam = (
  id: string,
  input: {
    name?: string;
    visibility?: TeamVisibility;
    join_password?: string | null;
    clear_password?: boolean;
  },
) => api.patch<TeamDetail>(`/teams/${id}`, input);

export const joinTeam = (id: string, password?: string) =>
  api.post<TeamDetail>(`/teams/${id}/join`, { password: password ?? null });

export const leaveTeam = (teamId: string, userId: string) =>
  api.delete<{ message: string }>(`/teams/${teamId}/members/${userId}`);

export const transferLeadership = (teamId: string, userId: string) =>
  api.post<TeamDetail>(`/teams/${teamId}/leader`, { user_id: userId });

export const requestToJoin = (teamId: string, message?: string) =>
  api.post<JoinRequest>(`/teams/${teamId}/join-requests`, { message: message ?? null });

export const listJoinRequests = (teamId: string) =>
  api.get<JoinRequest[]>(`/teams/${teamId}/join-requests`);

export const acceptJoinRequest = (teamId: string, requestId: string) =>
  api.post<TeamDetail>(`/teams/${teamId}/join-requests/${requestId}/accept`);

export const rejectJoinRequest = (teamId: string, requestId: string) =>
  api.post<{ message: string }>(`/teams/${teamId}/join-requests/${requestId}/reject`);
