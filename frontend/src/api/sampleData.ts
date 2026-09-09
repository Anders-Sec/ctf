import { api } from "./client";

export interface SampleDataSummary {
  categories: number;
  challenges: number;
  skills: number;
  hints: number;
  players: number;
  teams: number;
  solves: number;
  gates: number;
  achievements: number;
}

/** `standalone` builds a self-contained four-zone event; `dungeon` fills the
 *  real 22 zones with the real skills attached (spec 025). */
export type SampleDataMode = "standalone" | "dungeon";

export const generateSampleData = (mode: SampleDataMode = "standalone") =>
  api.post<SampleDataSummary>(`/admin/sample-data?mode=${mode}`);

export const purgeSampleData = () =>
  api.delete<{ message: string }>("/admin/sample-data");
