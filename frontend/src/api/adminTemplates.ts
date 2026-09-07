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
  readiness_path?: string;
}) => api.post<ContainerTemplate>("/admin/templates", input);

export const deleteTemplate = (id: string) =>
  api.delete<void>(`/admin/templates/${id}`);
