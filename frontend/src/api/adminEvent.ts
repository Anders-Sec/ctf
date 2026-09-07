import { api } from "./client";

export interface EventConfig {
  name: string;
  starts_at: string | null;
  ends_at: string | null;
  registration_open: boolean;
  assistant_enabled: boolean;
  /** The clock the gates actually use. Shown so an admin sets times against it. */
  server_time: string;
}

export const getEventConfig = () => api.get<EventConfig>("/admin/event-config");

export const updateEventConfig = (input: {
  name?: string;
  starts_at?: string | null;
  ends_at?: string | null;
  registration_open?: boolean;
  assistant_enabled?: boolean;
}) => api.patch<EventConfig>("/admin/event-config", input);
