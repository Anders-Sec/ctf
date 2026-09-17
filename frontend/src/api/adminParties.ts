import { api } from "./client";

/** Admin control over parties (spec 053). */

export interface PartySummary {
  team_id: string;
  name: string;
  visibility: "public" | "private";
  member_count: number;
  max_members: number;
  leader_user_id: string;
  leader_name: string | null;
  /** Disabled, or not seen in a day — the "leader went home" signal. */
  leader_absent: boolean;
  has_password: boolean;
  created_at: string;
  disbanded_at: string | null;
}

export interface PartyMember {
  user_id: string;
  display_name: string;
  role: string;
  joined_at: string;
  removed_at: string | null;
  removed_by_name: string | null;
  removal_reason: string | null;
  solve_count: number;
  xp: number;
}

export interface PendingJoinRequest {
  id: string;
  user_id: string;
  display_name: string;
  message: string | null;
  created_at: string;
}

export interface PartyDetail {
  team_id: string;
  name: string;
  visibility: "public" | "private";
  max_members: number;
  leader_user_id: string;
  has_password: boolean;
  disbanded_at: string | null;
  members: PartyMember[];
  join_requests: PendingJoinRequest[];
}

export interface EligibleMember {
  user_id: string;
  display_name: string;
}

export const listParties = (params: { search?: string; include_disbanded?: boolean } = {}) => {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.include_disbanded) query.set("include_disbanded", "true");
  const suffix = query.toString();
  return api.get<PartySummary[]>(`/admin/parties${suffix ? `?${suffix}` : ""}`);
};

export const getParty = (teamId: string) => api.get<PartyDetail>(`/admin/parties/${teamId}`);

export const listEligibleMembers = () =>
  api.get<EligibleMember[]>("/admin/parties/eligible-members");

export const updateParty = (
  teamId: string,
  input: {
    name?: string;
    visibility?: "public" | "private";
    max_members?: number;
    clear_join_password?: boolean;
    reason?: string;
  },
) => api.patch<PartyDetail>(`/admin/parties/${teamId}`, input);

export const transferLeadership = (teamId: string, userId: string) =>
  api.post<{ message: string }>(`/admin/parties/${teamId}/leader`, { user_id: userId });

export const addPartyMember = (teamId: string, userId: string, reason?: string) =>
  api.post<{ message: string }>(`/admin/parties/${teamId}/members`, {
    user_id: userId,
    reason: reason ?? null,
  });

export const removePartyMember = (teamId: string, userId: string) =>
  api.delete<{ message: string }>(`/admin/parties/${teamId}/members/${userId}`);

/** Routed off the member: the source is derivable, and naming both invites
 *  them to disagree. */
export const movePartyMember = (userId: string, toTeamId: string, reason?: string) =>
  api.post<{ message: string }>(`/admin/parties/members/${userId}/move`, {
    to_team_id: toTeamId,
    reason: reason ?? null,
  });

export const disbandParty = (teamId: string, reason?: string) =>
  api.post<{ message: string }>(`/admin/parties/${teamId}/disband`, { reason: reason ?? null });

export const decideJoinRequest = (teamId: string, requestId: string, accept: boolean) =>
  api.post<{ message: string }>(
    `/admin/parties/${teamId}/join-requests/${requestId}/${accept ? "accept" : "reject"}`,
    {},
  );
