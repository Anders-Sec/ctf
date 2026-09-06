import { api } from "./client";

export interface Participant {
  user_id: string;
  display_name: string;
}

export interface Finding {
  signal_type: string;
  subject_key: string;
  participants: Participant[];
  challenge_title: string | null;
  evidence: Record<string, unknown>;
  /** The boring reason this probably happened. Shown beside the evidence. */
  innocent_explanation: string;
  dismissed: boolean;
}

export interface SignalsResponse {
  counts: Record<string, number>;
  findings: Record<string, Finding[]>;
}

export interface TimelineEvent {
  at: string;
  kind: "attempt" | "solve" | "hint" | "party_join" | "party_leave";
  challenge: string | null;
  detail: string;
  ip: string | null;
}

export interface PlayerTimeline {
  user_id: string;
  display_name: string;
  events: TimelineEvent[];
}

export const getSignals = () => api.get<SignalsResponse>("/admin/signals");

export const dismissSignal = (signalType: string, subjectKey: string, note?: string) =>
  api.post<{ message: string }>("/admin/signals/dismiss", {
    signal_type: signalType,
    subject_key: subjectKey,
    note: note ?? null,
  });

export const getPlayerTimeline = (userId: string) =>
  api.get<PlayerTimeline>(`/admin/players/${userId}/timeline`);

/** Plain-language names. The console never says "violation". */
export const SIGNAL_LABELS: Record<string, string> = {
  shared_wrong_answer: "Identical unusual wrong answer",
  close_behind_solve: "Solve close behind another party",
  first_try_solver: "Correct on the first attempt, repeatedly",
  late_recruitment: "Joined a party late with solves in hand",
  steady_cadence: "Machine-regular submission timing",
  shared_ip: "Shared network address",
};
