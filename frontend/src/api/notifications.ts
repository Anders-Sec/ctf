import { api } from "./client";

/** What produced a notification. Drives the icon, never the delivery. */
export type NotificationKind =
  | "achievement"
  | "class_unlocked"
  | "zone_unlocked"
  | "level_up"
  | "ability_milestone"
  | "system";

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
