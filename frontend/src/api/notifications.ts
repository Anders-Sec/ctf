import { api } from "./client";

/**
 * What produced a notification. Drives the icon and the grouping, never the
 * delivery.
 *
 * **All nine the backend defines.** This listed six until spec 065 — `boss_kill`,
 * `announcement` and `dispatch` were missing, so anything built from this union
 * would have silently omitted announcements. A backend test asserts the two
 * lists match rather than trusting them to.
 */
export const NOTIFICATION_KINDS = [
  "achievement",
  "class_unlocked",
  "zone_unlocked",
  "level_up",
  "ability_milestone",
  "boss_kill",
  "announcement",
  "dispatch",
  "system",
] as const;

export type NotificationKind = (typeof NOTIFICATION_KINDS)[number];

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface NotificationFeed {
  unread: number;
  items: AppNotification[];
}

export const getNotifications = () => api.get<NotificationFeed>("/notifications");

export const markAllRead = () =>
  api.post<{ message: string }>("/notifications/read");

export const markRead = (id: string) =>
  api.post<{ message: string }>(`/notifications/${id}/read`);

/** Clear one row from the inbox. A soft dismiss server-side (spec 065 §4). */
export const dismissOne = (id: string) =>
  api.post<{ message: string }>(`/notifications/${id}/dismiss`);

/** Clear everything, or everything of the given kinds. Scoped so one tab's
 *  clear-all cannot take the other tab's rows with it. */
export const dismissMany = (kinds: NotificationKind[] = []) =>
  api.post<{ message: string }>("/notifications/dismiss", { kinds });

/** Null until earned — redacted server-side, so there is nothing here to
 *  un-blur in devtools (spec 028). */
export interface AchievementRow {
  id: string;
  name: string | null;
  description: string | null;
  earned: boolean;
  rarity: number | null;
}

export interface AchievementsResponse {
  earned: number;
  total: number;
  items: AchievementRow[];
  rarest: AchievementRow[];
}

export const getAchievements = () =>
  api.get<AchievementsResponse>("/character/achievements");
