import { api } from "./client";
import type { InstanceStatus } from "./instances";

export interface AdminInstance {
  id: string;
  challenge_id: string;
  challenge_title: string;
  /** Which image this is. One container can serve several challenges (spec 046). */
  template_name: string | null;
  status: InstanceStatus;
  owner_label: string;
  connection_url: string | null;
  created_at: string;
  expires_at: string;
  error: string | null;
}

export const getAdminInstances = () => api.get<AdminInstance[]>("/admin/instances");

export const forceTeardown = (id: string) => api.delete<void>(`/admin/instances/${id}`);
