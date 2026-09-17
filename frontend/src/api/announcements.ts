import { api } from "./client";

/**
 * Announcements (spec 054).
 *
 * The endpoint now returns the announcement rather than a bare recipient count:
 * the count alone was everything the old composer knew, and forgetting it was
 * the problem.
 */

export interface Announcement {
  id: string;
  title: string;
  body: string;
  audience: "everyone" | "staff";
  created_by_name: string | null;
  /** Set while pending — the one state that can still be edited or cancelled. */
  scheduled_for: string | null;
  sent_at: string | null;
  cancelled_at: string | null;
  recipient_count: number;
  /** Counted over the fan-out, never stored on the announcement. */
  read_count: number;
  created_at: string;
}

export const listAnnouncements = () => api.get<Announcement[]>("/admin/announcements");

export const createAnnouncement = (input: {
  title: string;
  body: string;
  audience?: "everyone" | "staff";
  /** Null sends now. A time already past also sends now. */
  scheduled_for?: string | null;
}) => api.post<Announcement>("/admin/announcements", input);

export const updateAnnouncement = (
  id: string,
  input: { title?: string; body?: string; scheduled_for?: string },
) => api.patch<Announcement>(`/admin/announcements/${id}`, input);

export const cancelAnnouncement = (id: string) =>
  api.post<Announcement>(`/admin/announcements/${id}/cancel`, {});
