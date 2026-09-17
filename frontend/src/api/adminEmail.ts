import { api } from "./client";

/** The email delivery log (spec 055). */

export type EmailKind = "magic_link" | "approval_notice" | "test";
/** "The relay accepted it", never "it arrived" — SMTP confirms nothing. */
export type EmailStatus = "sent" | "failed" | "not_configured";

export interface Delivery {
  id: string;
  kind: EmailKind;
  to_email: string;
  user_id: string | null;
  status: EmailStatus;
  error_type: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface DeliveryPage {
  total: number;
  entries: Delivery[];
}

export interface MailStatus {
  configured: boolean;
  window_minutes: number;
  sent: number;
  failed: number;
  failure_rate: number;
  /** Worth a banner. False below a minimum volume. */
  degraded: boolean;
}

export interface DeliveryFilters {
  kind?: EmailKind;
  status?: EmailStatus;
  user_id?: string;
  search?: string;
  limit?: number;
}

export const getMailStatus = () => api.get<MailStatus>("/admin/email/status");

export const listDeliveries = (filters: DeliveryFilters = {}) => {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString();
  return api.get<DeliveryPage>(`/admin/email/deliveries${suffix ? `?${suffix}` : ""}`);
};

/** Always to the caller's own address; there is no recipient to supply. */
export const sendTestEmail = () => api.post<{ message: string }>("/admin/email/test", {});
