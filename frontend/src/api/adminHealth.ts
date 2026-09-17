import { api } from "./client";

/** Staff-facing platform health (spec 057). */

export interface HealthCheck {
  name: string;
  /** "not_configured" is a valid state, not a fault. */
  state: "ok" | "degraded" | "down" | "not_configured";
  duration_ms: number | null;
  detail: string | null;
}

export interface HealthReport {
  checked_at: string;
  checks: HealthCheck[];
  connections: { scoreboard: number };
  build: { version: string; environment: string };
  load: {
    window_minutes: number;
    requests_per_minute: number;
    p95_ms: number;
    errors: number;
    /** Resets on restart — which is itself informative. */
    uptime_seconds: number;
  };
}

export const getPlatformHealth = () => api.get<HealthReport>("/admin/health");
