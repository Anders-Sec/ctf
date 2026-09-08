import { api } from "./client";

export interface SampleDataSummary {
  categories: number;
  challenges: number;
  skills: number;
  classes: number;
  hints: number;
  players: number;
  teams: number;
  solves: number;
  gates: number;
}

export const generateSampleData = () =>
  api.post<SampleDataSummary>("/admin/sample-data");

export const purgeSampleData = () =>
  api.delete<{ message: string }>("/admin/sample-data");
