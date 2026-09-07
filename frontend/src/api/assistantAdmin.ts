import { api } from "./client";

export interface AssistantFinding {
  id: string;
  created_at: string;
  layer: "integrity" | "safety";
  rule: string;
  severity: "low" | "medium" | "high";
  action: "logged" | "deflected";
  player_name: string;
  challenge_id: string | null;
  question: string | null;
  reply: string | null;
  detail: Record<string, unknown>;
}

export interface FindingsPage {
  findings: AssistantFinding[];
  total: number;
}

export interface FindingFilters {
  layer?: "integrity" | "safety";
  action?: "logged" | "deflected";
  includeStaff?: boolean;
}

export function getFindings(filters: FindingFilters = {}) {
  const params = new URLSearchParams();
  if (filters.layer) params.set("layer", filters.layer);
  if (filters.action) params.set("action", filters.action);
  if (filters.includeStaff) params.set("include_staff", "true");
  const query = params.toString();
  return api.get<FindingsPage>(`/admin/assistant/findings${query ? `?${query}` : ""}`);
}

export const RULE_LABELS: Record<string, string> = {
  answer_verbatim: "Reply contained a real answer",
  answer_regex: "Reply matched an answer rule",
  flag_shaped: "Reply was flag-shaped",
  injection_attempt: "Prompt-injection attempt",
  integrity_scanner_error: "Integrity scanner failed",
  malware_build: "Malware construction",
  credential_harvesting: "Credential harvesting",
  real_world_target: "Named a real-world target",
  safety_scanner_error: "Safety scanner failed",
  judge_escalation: "Escalated by the judge",
};
