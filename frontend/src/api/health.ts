import { api } from "./client";

export interface VersionInfo {
  version: string;
  environment: string;
}

export interface ReadinessInfo {
  status: "ok" | "degraded";
  postgres: "ok" | "error";
  redis: "ok" | "error";
}

export const getVersion = () => api.get<VersionInfo>("/version");
export const getReadiness = () => api.get<ReadinessInfo>("/health/ready");
