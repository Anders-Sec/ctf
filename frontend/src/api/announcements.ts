import { api } from "./client";

export interface AnnouncementResult {
  /** How many players it reached. Zero is a real answer. */
  recipients: number;
}

export const sendAnnouncement = (input: {
  title: string;
  body: string;
  link?: string | null;
}) => api.post<AnnouncementResult>("/admin/announcements", input);
