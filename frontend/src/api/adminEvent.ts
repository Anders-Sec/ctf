import type { ThemeId } from "../theme/themes";
import { api } from "./client";

export interface EventConfig {
  name: string;
  starts_at: string | null;
  ends_at: string | null;
  registration_open: boolean;
  assistant_enabled: boolean;
  /** Dim locked zones on the dungeon map (spec 017). Presentation only. */
  fog_of_war: boolean;
  /** Served to everyone who has not chosen a theme. Null means the platform default. */
  default_theme: ThemeId | null;
  /** The server's roster, so the picker renders from it rather than a second copy. */
  themes: ThemeId[];
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
  fog_of_war?: boolean;
  default_theme?: ThemeId | null;
}) => api.patch<EventConfig>("/admin/event-config", input);
