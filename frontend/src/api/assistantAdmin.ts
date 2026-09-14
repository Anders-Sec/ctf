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
  /** Null means nobody has looked at it yet. */
  acknowledged_at: string | null;
}

export interface FindingsPage {
  findings: AssistantFinding[];
  total: number;
}

export interface FindingFilters {
  layer?: "integrity" | "safety";
  action?: "logged" | "deflected";
  severity?: "low" | "medium" | "high";
  rule?: string;
  /** Default view: a flat feed works for twenty findings, not two thousand. */
  unreviewed?: boolean;
  includeStaff?: boolean;
}

export function getFindings(filters: FindingFilters = {}) {
  const params = new URLSearchParams();
  if (filters.layer) params.set("layer", filters.layer);
  if (filters.action) params.set("action", filters.action);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.rule) params.set("rule", filters.rule);
  if (filters.unreviewed) params.set("unreviewed", "true");
  if (filters.includeStaff) params.set("include_staff", "true");
  const query = params.toString();
  return api.get<FindingsPage>(`/admin/assistant/findings${query ? `?${query}` : ""}`);
}

export interface TermsSummary {
  /** The hash of the live terms file. A revised file is a new version. */
  version: string;
  accepted: number;
  outstanding: number;
  /** Only when asked for — useful before an event, less so during one. */
  outstanding_names: string[] | null;
}

export const getTermsSummary = (includeNames = false) =>
  api.get<TermsSummary>(
    `/admin/assistant/terms${includeNames ? "?include_names=true" : ""}`,
  );

export const RULE_LABELS: Record<string, string> = {
  // The integrity layer was retired by spec 033 — on a prompt-injection ladder
  // the flag reaching the player is the win condition. These are kept only so
  // findings recorded before that still render with a name.
  answer_verbatim: "Reply contained a real answer (retired rule)",
  answer_regex: "Reply matched an answer rule (retired rule)",
  flag_shaped: "Reply was flag-shaped (retired rule)",
  injection_attempt: "Prompt-injection attempt (retired rule)",
  integrity_scanner_error: "Integrity scanner failed (retired rule)",
  malware_build: "Malware construction",
  credential_harvesting: "Credential harvesting",
  real_world_target: "Named a real-world target",
  safety_scanner_error: "Safety scanner failed",
  judge_escalation: "Escalated by the judge",
};

// --- The console (spec 034) -------------------------------------------------

export interface MetricsWindow {
  turns: number;
  active_sessions: number;
  deflections: number;
  errors: number;
  median_latency_ms: number | null;
  p95_latency_ms: number | null;
  upstream_calls: number;
  /** A level 5 turn costs five. The capacity figure spec 033 left visible. */
  calls_per_turn: number | null;
}

export interface Rung {
  level: number;
  name: string;
  turns: number;
  solves: number;
  /** Must stay near zero — a climb means the model is inventing flags. */
  decoys: number;
  gates: Record<string, number>;
  players: number;
}

export interface Metrics {
  generated_at: string;
  windows: Record<string, MetricsWindow>;
  errors_by_reason: Record<string, number>;
  findings_by_rule: Record<string, number>;
  rungs: Rung[];
  total_turns: number;
  total_conversations: number;
  unacknowledged_findings: number;
}

export interface AssistantHealth {
  enabled: boolean;
  configured: boolean;
  reachable: boolean;
  model: string | null;
  breaker_open: boolean;
  consecutive_failures: number;
  retry_after_seconds: number;
  in_flight: number;
  average_latency_ms: number | null;
  error: string | null;
}

export interface Session {
  user_id: string;
  player_name: string;
  turns: number;
  last_message_at: string | null;
  ladder_level: number;
  findings: number;
  blocked: boolean;
  from_staff: boolean;
}

export interface TranscriptTurn {
  id: string;
  role: string;
  content: string;
  original_content: string | null;
  reasoning_content: string | null;
  ladder_level: number | null;
  trace: string[] | null;
  latency_ms: number | null;
  upstream_calls: number | null;
  error: string | null;
  created_at: string;
}

export interface Transcript {
  user_id: string;
  player_name: string;
  /** False when retention has purged the conversation. */
  exists: boolean;
  turns: TranscriptTurn[];
}

export const getMetrics = () => api.get<Metrics>("/admin/assistant/metrics");

export const getHealth = () => api.get<AssistantHealth>("/admin/assistant/health");

export const getSessions = (minutes: number | null) =>
  api.get<{ sessions: Session[] }>(
    `/admin/assistant/sessions?minutes=${minutes ?? 0}`,
  );

/** Admin only, and opening one is audited. */
export const getTranscript = (userId: string) =>
  api.get<Transcript>(`/admin/assistant/sessions/${userId}`);

export const acknowledgeFinding = (id: string) =>
  api.post<{ message: string }>(`/admin/assistant/findings/${id}/acknowledge`);

export const setAssistantBlock = (userId: string, blocked: boolean) =>
  api.post<{ message: string }>(`/admin/users/${userId}/assistant-block`, { blocked });

export const purgeConversations = () =>
  api.post<{ purged: number }>("/admin/assistant/purge");
