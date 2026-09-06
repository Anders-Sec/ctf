import { api } from "./client";

export type UserSource = "entra" | "guest";
export type UserRole = "player" | "organizer" | "admin";
export type UserStatus = "pending_approval" | "active" | "disabled";

export interface User {
  id: string;
  email: string;
  display_name: string;
  source: UserSource;
  role: UserRole;
  status: UserStatus;
  has_avatar: boolean;
  created_at: string;
}

/**
 * Resolved server-side so the client never re-implements the authorization
 * matrix — and so it cannot drift from the rules the API actually enforces.
 */
export interface Capabilities {
  manage_party: boolean;
  play: boolean;
  view_scoreboard: boolean;
  view_admin: boolean;
  administer: boolean;
  blocked_reason:
    | "account_pending_approval"
    | "account_disabled"
    | "event_not_started"
    | "event_ended"
    | null;
}

export interface TeamSummary {
  id: string;
  name: string;
  is_leader: boolean;
}

export interface EventSummary {
  name: string;
  starts_at: string | null;
  ends_at: string | null;
  registration_open: boolean;
  /** The clock that actually decides. The client's own is decorative. */
  server_time: string;
}

export interface Me {
  user: User;
  team: TeamSummary | null;
  capabilities: Capabilities;
  event: EventSummary | null;
}

export const getMe = () => api.get<Me>("/auth/me");

export const requestMagicLink = (email: string) =>
  api.post<{ message: string }>("/auth/magic-link", { email });

export const verifyMagicLink = (token: string) =>
  api.post<{ message: string }>("/auth/magic-link/verify", { token });

export const logout = () => api.post<{ message: string }>("/auth/logout");

export const updateDisplayName = (display_name: string) =>
  api.patch<User>("/auth/me", { display_name });

export const avatarUrl = (userId: string) => `/api/users/${userId}/avatar`;

/** A full navigation, not a fetch: the provider redirect must own the tab. */
export const startEntraLogin = () => {
  window.location.href = "/api/auth/entra/login";
};
