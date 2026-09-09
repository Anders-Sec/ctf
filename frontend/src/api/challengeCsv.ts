import { api } from "./client";

/** Row and column, because "invalid difficulty" alone in a 242-row file tells
 *  an admin nothing about where to look (spec 026). */
export interface RowError {
  row: number;
  column: string;
  problem: string;
}

export interface ImportReport {
  created: number;
  updated: number;
  skipped: number;
  dry_run: boolean;
  errors: RowError[];
}

/** Downloads are plain links rather than fetches: the browser saves the file
 *  from the Content-Disposition header, which an XHR would have to reimplement. */
export const TEMPLATE_URL = "/api/admin/challenges/template.csv";
export const EXPORT_URL = "/api/admin/challenges/export.csv";

export const importChallenges = (file: File, dryRun: boolean) => {
  const body = new FormData();
  body.append("file", file);
  return api.post<ImportReport>(
    `/admin/challenges/import?dry_run=${dryRun}`,
    body,
  );
};
