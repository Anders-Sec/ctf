import { api } from "./client";

export interface ContainerTemplate {
  id: string;
  name: string;
  image: string;
  image_tag: string;
  container_port: number;
  protocol: string;
  ttl_seconds: number;
  injects_answer: boolean;
  /** One container for every challenge bound to this template (spec 046). */
  shared_instance: boolean;
  cpu_limit: string;
  memory_limit: string;
  readiness_path: string;
}

export const listTemplates = () =>
  api.get<ContainerTemplate[]>("/admin/templates");

export const createTemplate = (input: {
  name: string;
  image: string;
  image_tag?: string;
  container_port?: number;
  ttl_seconds?: number;
  injects_answer?: boolean;
  shared_instance?: boolean;
  cpu_limit?: string;
  memory_limit?: string;
  readiness_path?: string;
}) => api.post<ContainerTemplate>("/admin/templates", input);

/**
 * Correcting a template in place. Deleting and recreating is not equivalent:
 * the challenge FK is ON DELETE SET NULL, so a delete unbinds every challenge
 * that used it and they have to be re-imported.
 */
export const updateTemplate = (id: string, input: Partial<ContainerTemplate>) =>
  api.patch<ContainerTemplate>(`/admin/templates/${id}`, input);

export const deleteTemplate = (id: string) =>
  api.delete<void>(`/admin/templates/${id}`);
