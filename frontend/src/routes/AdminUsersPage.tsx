import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { approveUsers, listUsers, type AdminUser, type UserFilters } from "../api/admin";
import type { UserStatus } from "../api/auth";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import UserDetailDrawer from "../components/UserDetailDrawer";

/**
 * The roster (spec 052).
 *
 * Replaces the approvals-only page, whose own comment admitted it was a
 * placeholder: *"Minimal by design — spec 006 owns the real admin tooling; this
 * exists because guests are dead in the water without someone to let them in."*
 * Spec 006 never came back for it.
 *
 * The approval queue is a filter here, not a separate page. It is how the page
 * is most often entered during the event; it just is not a different thing.
 */

const CHIPS: { label: string; status?: UserStatus; role?: "staff" }[] = [
  { label: "All" },
  { label: "Pending", status: "pending_approval" },
  { label: "Active", status: "active" },
  { label: "Disabled", status: "disabled" },
  { label: "Staff", role: "staff" },
];

export default function AdminUsersPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openUserId, setOpenUserId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const status = params.get("status") as UserStatus | null;
  const staffOnly = params.get("staff") === "1";

  const filters: UserFilters = {
    status: status ?? undefined,
    // The API filters one role at a time, and "staff" is two of them. Organizer
    // is the rarer account, so admin is the one worth showing by default here.
    role: staffOnly ? "admin" : undefined,
    search: params.get("search") ?? undefined,
    limit: 200,
  };

  const users = useQuery({
    queryKey: ["admin", "users", filters],
    queryFn: () => listUsers(filters),
  });

  const approve = useMutation({
    mutationFn: (ids: string[]) => approveUsers(ids),
    onSuccess: async () => {
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "dashboard"] });
    },
  });

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setSelected(new Set());
  };

  const rows = users.data?.users ?? [];
  const pendingSelected = rows.filter(
    (user) => selected.has(user.id) && user.status === "pending_approval",
  );

  const toggle = (id: string) => {
    setSelected((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <main className="p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Users</h1>
        <p className="mt-2 text-sm text-content-muted">
          Everyone who can sign in, and what state they are in.
        </p>
      </header>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {CHIPS.map((chip) => {
          const active = chip.role
            ? staffOnly
            : !staffOnly && (status ?? undefined) === chip.status;
          return (
            <button
              key={chip.label}
              type="button"
              onClick={() => {
                const next = new URLSearchParams(params);
                next.delete("status");
                next.delete("staff");
                if (chip.status) next.set("status", chip.status);
                if (chip.role) next.set("staff", "1");
                setParams(next, { replace: true });
                setSelected(new Set());
              }}
              aria-pressed={active}
              className={`rounded-full border px-3 py-1 text-sm ${
                active ? "border-accent bg-accent/10 font-medium" : "border-border"
              }`}
            >
              {chip.label}
            </button>
          );
        })}

        <input
          value={params.get("search") ?? ""}
          onChange={(event) => set("search", event.target.value)}
          placeholder="Search name or email"
          aria-label="Search users"
          className="ml-auto rounded border border-border-strong bg-surface-raised px-2 py-1 text-sm"
        />
      </div>

      <ErrorMessage error={users.error ?? approve.error} />

      {pendingSelected.length > 0 && (
        // The one bulk action that matters: 200 guests do not get approved one
        // at a time, and the endpoint has always taken a list.
        <div className="mt-4 flex items-center gap-3 rounded border border-accent bg-accent/10 px-3 py-2 text-sm">
          <span>
            {pendingSelected.length} selected and waiting for approval
          </span>
          <button
            type="button"
            disabled={approve.isPending}
            onClick={() => approve.mutate(pendingSelected.map((user) => user.id))}
            className="rounded bg-accent px-3 py-1 text-accent-content disabled:opacity-50"
          >
            Approve
          </button>
        </div>
      )}

      {users.isPending ? (
        <Spinner label="Reading the roster…" />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-content-muted">
              <tr className="border-b border-border">
                <th className="w-8 py-2" />
                <th className="py-2 pr-3 font-medium">Name</th>
                <th className="py-2 pr-3 font-medium">Email</th>
                <th className="py-2 pr-3 font-medium">Source</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Party</th>
                <th className="py-2 pr-3 text-right font-medium">Solves</th>
                <th className="py-2 pr-3 text-right font-medium">XP</th>
                <th className="py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => (
                <Row
                  key={user.id}
                  user={user}
                  checked={selected.has(user.id)}
                  onToggle={() => toggle(user.id)}
                  onOpen={() => setOpenUserId(user.id)}
                />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-6 text-content-muted">
                    Nobody matches that.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {openUserId && (
        <UserDetailDrawer userId={openUserId} onClose={() => setOpenUserId(null)} />
      )}
    </main>
  );
}

function Row({
  user,
  checked,
  onToggle,
  onOpen,
}: {
  user: AdminUser;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  return (
    <tr className="border-b border-border">
      <td className="py-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${user.display_name}`}
        />
      </td>
      <td className="py-2 pr-3">
        <button type="button" onClick={onOpen} className="text-accent-strong underline">
          {user.display_name}
        </button>
        {/* Only when it is not "player": a column of the same word 200 times
            tells you nothing, while a staff account should stand out. */}
        {user.role !== "player" && (
          <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-xs uppercase tracking-wide text-content-muted">
            {user.role}
          </span>
        )}
      </td>
      <td className="py-2 pr-3 text-content-muted">{user.email}</td>
      <td className="py-2 pr-3 text-content-muted">{user.source}</td>
      <td className="py-2 pr-3">
        <StatusBadge status={user.status} />
      </td>
      <td className="py-2 pr-3 text-content-muted">{user.party_name ?? "—"}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{user.solve_count}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{user.xp}</td>
      <td className="py-2 text-content-muted">
        {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "never"}
      </td>
    </tr>
  );
}

function StatusBadge({ status }: { status: UserStatus }) {
  const tone =
    status === "active"
      ? "text-success"
      : status === "disabled"
        ? "text-danger"
        : "text-warning";
  // The word, always. Colour is the fast path, never the only one.
  return <span className={tone}>{status.replace("_", " ")}</span>;
}
