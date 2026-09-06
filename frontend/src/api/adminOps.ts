import { api } from "./client";
import type { ChallengeState } from "./challenges";

export interface Adjustment {
  id: string;
  user_id: string | null;
  team_id: string | null;
  subject_name: string | null;
  points: number;
  reason: string;
  created_by_user_id: string | null;
  created_by_name: string | null;
  reverses_id: string | null;
  /** Set when a later entry cancelled this one. Shown struck through, never hidden. */
  reversed_by_id: string | null;
  created_at: string;
}

export type ReportStatus = "open" | "acknowledged" | "dismissed" | "resolved";

export interface Report {
  id: string;
  challenge_id: string;
  challenge_title: string | null;
  user_id: string;
  reporter_name: string | null;
  message: string;
  status: ReportStatus;
  resolution_note: string | null;
  created_at: string;
}

export interface ChallengeHealth {
  challenge_id: string;
  title: string;
  state: ChallengeState;
  solve_count: number;
  attempt_count: number;
  open_reports: number;
  suspected_broken: boolean;
  suspiciously_easy: boolean;
}

export interface Dashboard {
  generated_at: string;
  event: {
    name: string | null;
    starts_at: string | null;
    ends_at: string | null;
    running: boolean;
    server_time: string;
  };
  pulse: {
    solves_5m: number;
    solves_15m: number;
    solves_60m: number;
    submissions_15m: number;
    active_players_15m: number;
  };
  attention: {
    open_reports: number;
    pending_approvals: number;
    drafts_after_start: number;
    published_without_answers: { challenge_id: string; title: string }[];
    suspected_broken: { challenge_id: string; title: string; attempts: number }[];
  };
  containers: { available: boolean; note: string };
}

export interface AuditEntry {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_name: string | null;
  target_type: string;
  target_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  request_id: string | null;
  created_at: string;
}

export const getDashboard = () => api.get<Dashboard>("/admin/dashboard");
export const getChallengeHealth = () => api.get<ChallengeHealth[]>("/admin/challenge-health");
export const listAdjustments = () => api.get<Adjustment[]>("/admin/adjustments");

export const createAdjustment = (input: {
  user_id?: string;
  team_id?: string;
  points: number;
  reason: string;
}) => api.post<Adjustment>("/admin/adjustments", input);

export const reverseAdjustment = (id: string, reason: string) =>
  api.post<Adjustment>(`/admin/adjustments/${id}/reverse`, { reason });

export const listReports = (status?: ReportStatus) =>
  api.get<Report[]>(`/admin/reports${status ? `?status=${status}` : ""}`);

export const triageReport = (id: string, status: ReportStatus, note?: string) =>
  api.post<{ message: string }>(`/admin/reports/${id}/status`, { status, note: note ?? null });

export const listAudit = (action?: string) =>
  api.get<AuditEntry[]>(`/admin/audit-log${action ? `?action=${action}` : ""}`);

export const reportChallenge = (challengeId: string, message: string) =>
  api.post<Report>(`/challenges/${challengeId}/report`, { message });
