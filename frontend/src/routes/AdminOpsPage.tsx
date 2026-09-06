import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createAdjustment,
  listAdjustments,
  listReports,
  reverseAdjustment,
  triageReport,
  type Adjustment,
  type Report,
} from "../api/adminOps";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/** Score overrides and the broken-challenge queue. */
export default function AdminOpsPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;

  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Operations</h1>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          You have read-only access. Only admins can adjust scores or triage reports.
        </p>
      )}

      <ReportsSection canWrite={canWrite} />
      <AdjustmentsSection canWrite={canWrite} />
    </main>
  );
}

function ReportsSection({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient();
  const reports = useQuery({
    queryKey: ["admin", "reports", "open"],
    queryFn: () => listReports("open"),
    refetchInterval: 15_000,
  });

  const triage = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "resolved" | "dismissed" }) =>
      triageReport(id, status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "reports"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "dashboard"] });
    },
  });

  return (
    <section className="mt-8">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Broken-challenge reports
      </h2>
      <ErrorMessage error={reports.error ?? triage.error} />

      {reports.isPending ? (
        <Spinner />
      ) : (reports.data ?? []).length === 0 ? (
        <p className="mt-3 text-muted">Nothing reported.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {(reports.data ?? []).map((report: Report) => (
            <li key={report.id} className="rounded-lg border border-stone bg-white/60 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{report.challenge_title ?? "Unknown challenge"}</p>
                  <p className="mt-1 text-sm">{report.message}</p>
                  <p className="mt-1 text-xs text-muted">
                    {report.reporter_name ?? "Someone"} ·{" "}
                    {new Date(report.created_at).toLocaleString()}
                  </p>
                </div>
                {canWrite && (
                  <span className="flex shrink-0 gap-2">
                    <button
                      onClick={() => triage.mutate({ id: report.id, status: "resolved" })}
                      className="rounded bg-ink px-3 py-1 text-xs text-parchment"
                    >
                      Fixed
                    </button>
                    <button
                      onClick={() => triage.mutate({ id: report.id, status: "dismissed" })}
                      className="rounded border border-stone px-3 py-1 text-xs"
                    >
                      Nothing wrong
                    </button>
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AdjustmentsSection({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<"user" | "team">("team");
  const [targetId, setTargetId] = useState("");
  const [points, setPoints] = useState("");
  const [reason, setReason] = useState("");

  const adjustments = useQuery({
    queryKey: ["admin", "adjustments"],
    queryFn: listAdjustments,
  });

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "adjustments"] });
    await queryClient.invalidateQueries({ queryKey: ["scoreboard"] });
  };

  const create = useMutation({
    mutationFn: () =>
      createAdjustment({
        ...(target === "user" ? { user_id: targetId } : { team_id: targetId }),
        points: Number(points),
        reason: reason.trim(),
      }),
    onSuccess: async () => {
      setTargetId("");
      setPoints("");
      setReason("");
      await reload();
    },
  });

  const reverse = useMutation({
    mutationFn: (id: string) => reverseAdjustment(id, "Reversed by an organiser"),
    onSuccess: reload,
  });

  return (
    <section className="mt-10">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
        Score adjustments
      </h2>

      {canWrite && (
        <form
          className="mt-3 rounded-lg border border-stone bg-white/60 p-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-[8rem_1fr_7rem]">
            <label className="text-sm">
              Applies to
              <select
                value={target}
                onChange={(event) => setTarget(event.target.value as "user" | "team")}
                className="mt-1 w-full rounded border border-stone px-3 py-2"
              >
                <option value="team">A party</option>
                <option value="user">A player</option>
              </select>
            </label>
            <label className="text-sm">
              {target === "team" ? "Party" : "Player"} id
              <input
                required
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
                className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono text-sm"
              />
            </label>
            <label className="text-sm">
              Points
              <input
                required
                type="number"
                value={points}
                onChange={(event) => setPoints(event.target.value)}
                className="mt-1 w-full rounded border border-stone px-3 py-2"
                placeholder="±"
              />
            </label>
          </div>

          <label className="mt-3 block text-sm">
            Reason
            <input
              required
              minLength={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="mt-1 w-full rounded border border-stone px-3 py-2"
              placeholder="Compensation for a broken challenge"
            />
          </label>

          <p className="mt-2 text-xs text-muted">
            {target === "team"
              ? "Applied to the party once. No member's personal score changes, and it stays with the party through joins, departures and leadership handovers."
              : "Applied to that player, and so to whichever party they are in."}
          </p>

          <button
            type="submit"
            disabled={create.isPending}
            className="mt-3 rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
          >
            Apply adjustment
          </button>
          <ErrorMessage error={create.error ?? reverse.error} />
        </form>
      )}

      {adjustments.isPending ? (
        <Spinner />
      ) : (adjustments.data ?? []).length === 0 ? (
        <p className="mt-3 text-muted">No adjustments have been made.</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-2">
          {(adjustments.data ?? []).map((row: Adjustment) => (
            <li
              key={row.id}
              className={`flex items-center gap-3 rounded border border-stone bg-white/60 px-3 py-2 text-sm ${
                row.reversed_by_id ? "line-through opacity-60" : ""
              }`}
            >
              <span className="w-16 shrink-0 text-right font-semibold tabular-nums">
                {row.points > 0 ? `+${row.points}` : row.points}
              </span>
              <span className="flex-1">
                {row.subject_name ?? "Unknown"}
                {row.team_id && <span className="ml-1 text-xs text-muted">(party)</span>}
                <span className="block text-xs text-muted">
                  {row.reason} · {row.created_by_name ?? "system"}
                </span>
              </span>
              {/* A reversed entry stays visible: the record of the decision is the point. */}
              {canWrite && !row.reversed_by_id && !row.reverses_id && (
                <button
                  onClick={() => reverse.mutate(row.id)}
                  className="shrink-0 text-xs underline"
                >
                  Reverse
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
