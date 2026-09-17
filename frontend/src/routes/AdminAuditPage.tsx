import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  listAudit,
  listAuditActions,
  type AuditEntry,
  type AuditFilters,
} from "../api/adminOps";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * The audit log (spec 051 §2).
 *
 * The record has been written correctly all along — approvals, kicks, event
 * config, score overrides, challenge edits, instance teardowns — and has never
 * been readable without a database client. Phase 1's Definition of Done asked
 * for it.
 *
 * Arrived at from context more often than from the sidebar, so every filter is
 * in the URL: a link to "everything that happened to this player" is the useful
 * form, and spec 052 and 053 both link in that way.
 */

const PAGE_SIZE = 100;

/** The recent past is nearly always the question during an event. */
function twentyFourHoursAgo(): string {
  return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

export default function AdminAuditPage() {
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);

  const filters: AuditFilters = {
    action: params.get("action") ?? undefined,
    actor_user_id: params.get("actor_user_id") ?? undefined,
    target_type: params.get("target_type") ?? undefined,
    search: params.get("search") ?? undefined,
    since: params.get("since") ?? twentyFourHoursAgo(),
    until: params.get("until") ?? undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setOffset(0);
  };

  const page = useQuery({
    queryKey: ["admin", "audit", filters],
    queryFn: () => listAudit(filters),
  });
  const actions = useQuery({
    queryKey: ["admin", "audit", "actions"],
    queryFn: listAuditActions,
  });

  const total = page.data?.total ?? 0;

  return (
    <main className="p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Audit Log</h1>
        <p className="mt-2 text-sm text-content-muted">
          Every consequential action, with who did it and why. Append-only — nothing here can be
          edited or removed.
        </p>
      </header>

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-content-muted">Action</span>
          <select
            value={params.get("action") ?? ""}
            onChange={(event) => set("action", event.target.value)}
            className="rounded border border-border-strong bg-surface-raised px-2 py-1"
          >
            <option value="">Any</option>
            {(actions.data ?? []).map((action) => (
              <option key={action} value={action}>
                {action}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="mb-1 block text-content-muted">Target type</span>
          <input
            value={params.get("target_type") ?? ""}
            onChange={(event) => set("target_type", event.target.value)}
            placeholder="user, team, challenge…"
            className="rounded border border-border-strong bg-surface-raised px-2 py-1"
          />
        </label>

        <label className="text-sm">
          <span className="mb-1 block text-content-muted">Since</span>
          <input
            type="datetime-local"
            value={(params.get("since") ?? twentyFourHoursAgo()).slice(0, 16)}
            onChange={(event) => set("since", event.target.value)}
            className="rounded border border-border-strong bg-surface-raised px-2 py-1"
          />
        </label>

        <label className="flex-1 text-sm">
          <span className="mb-1 block text-content-muted">Search reasons</span>
          <input
            value={params.get("search") ?? ""}
            onChange={(event) => set("search", event.target.value)}
            placeholder="why something happened"
            className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1"
          />
        </label>

        {[...params.keys()].length > 0 && (
          <button
            type="button"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
            className="rounded border border-border px-3 py-1 text-sm hover:bg-surface-sunken"
          >
            Clear
          </button>
        )}
      </div>

      <ErrorMessage error={page.error ?? actions.error} />

      {!page.data ? (
        <Spinner label="Reading the record…" />
      ) : (
        <>
          <p className="mt-4 text-sm text-content-muted">
            {total} {total === 1 ? "entry" : "entries"}
            {total > PAGE_SIZE && ` · showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`}
          </p>

          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-content-muted">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Actor</th>
                  <th className="py-2 pr-3 font-medium">Action</th>
                  <th className="py-2 pr-3 font-medium">Target</th>
                  <th className="py-2 pr-3 font-medium">Reason</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {page.data.entries.map((entry) => (
                  <Row key={entry.id} entry={entry} />
                ))}
                {page.data.entries.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-content-muted">
                      Nothing recorded in this window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {total > PAGE_SIZE && (
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((was) => Math.max(0, was - PAGE_SIZE))}
                className="rounded border border-border px-3 py-1 text-sm disabled:opacity-40"
              >
                Newer
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((was) => was + PAGE_SIZE)}
                className="rounded border border-border px-3 py-1 text-sm disabled:opacity-40"
              >
                Older
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function Row({ entry }: { entry: AuditEntry }) {
  const [open, setOpen] = useState(false);
  const when = new Date(entry.created_at);
  const hasDetail = Object.keys(entry.metadata ?? {}).length > 0 || entry.request_id;

  return (
    <>
      <tr className="border-b border-border align-top">
        {/* Absolute first: you cannot reconstruct a timeline from "3 hours ago". */}
        <td className="py-2 pr-3 tabular-nums">
          {when.toLocaleString()}
          <span className="block text-xs text-content-faint">{relative(when)}</span>
        </td>
        <td className="py-2 pr-3">
          {/* Not an unknown person: scheduled cleanup and automatic leadership
              transfer act on nobody's behalf. */}
          {entry.actor_name ?? <span className="text-content-muted">system</span>}
        </td>
        {/* The dotted verb as it is. Inventing friendly names for thirty of them
            would create a translation table to keep in sync. */}
        <td className="py-2 pr-3 font-mono text-xs">{entry.action}</td>
        <td className="py-2 pr-3">
          {entry.target_type}
          {entry.target_id && (
            <span className="block font-mono text-xs text-content-faint">
              {entry.target_id.slice(0, 8)}
            </span>
          )}
        </td>
        <td className="py-2 pr-3">{entry.reason ?? ""}</td>
        <td className="py-2">
          {hasDetail && (
            <button
              type="button"
              onClick={() => setOpen((was) => !was)}
              aria-expanded={open}
              className="text-xs text-accent-strong underline"
            >
              {open ? "Hide" : "Details"}
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border">
          <td colSpan={6} className="bg-surface-sunken px-3 py-2">
            <pre className="overflow-x-auto text-xs">
              {JSON.stringify(entry.metadata, null, 2)}
            </pre>
            {entry.request_id && (
              // Ties the entry to the application logs. In the drawer rather
              // than a column: it is noise in a table read for human reasons.
              <p className="mt-1 font-mono text-xs text-content-faint">
                request {entry.request_id}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function relative(when: Date): string {
  const seconds = Math.round((Date.now() - when.getTime()) / 1000);
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}
