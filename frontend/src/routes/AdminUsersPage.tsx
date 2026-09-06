import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveUsers, listUsers } from "../api/admin";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * The approval queue. Minimal by design — spec 006 owns the real admin tooling;
 * this exists because guests are dead in the water without someone to let
 * them in.
 */
export default function AdminUsersPage() {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const pending = useQuery({
    queryKey: ["admin", "users", "pending_approval"],
    queryFn: () => listUsers({ status: "pending_approval" }),
  });

  const approve = useMutation({
    mutationFn: (ids: string[]) => approveUsers(ids),
    onSuccess: async () => {
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
  });

  const canApprove = me?.capabilities.administer ?? false;
  const users = pending.data?.users ?? [];

  const toggle = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Approval queue</h1>
        <span className="text-muted">{pending.data?.total ?? 0} waiting</span>
      </header>

      {!canApprove && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          You have read-only access. Only admins can approve accounts.
        </p>
      )}

      <ErrorMessage error={approve.error} />

      {pending.isPending ? (
        <Spinner />
      ) : users.length === 0 ? (
        <p className="mt-6 text-muted">Nobody is waiting. The gate is clear.</p>
      ) : (
        <>
          {canApprove && (
            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={() => approve.mutate([...selected])}
                disabled={selected.size === 0 || approve.isPending}
                className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
              >
                Approve selected ({selected.size})
              </button>
              <button
                onClick={() => approve.mutate(users.map((user) => user.id))}
                disabled={approve.isPending}
                className="rounded border border-ink px-4 py-2 text-sm"
              >
                Approve all {users.length}
              </button>
            </div>
          )}

          <ul className="mt-4 flex flex-col gap-2">
            {users.map((user) => (
              <li
                key={user.id}
                className="flex items-center gap-3 rounded-lg border border-stone bg-white/60 p-3"
              >
                {canApprove && (
                  <input
                    type="checkbox"
                    aria-label={`Select ${user.email}`}
                    checked={selected.has(user.id)}
                    onChange={() => toggle(user.id)}
                  />
                )}
                <span className="flex-1">
                  <span className="font-medium">{user.display_name}</span>
                  <span className="block text-sm text-muted">{user.email}</span>
                </span>
                <span className="text-xs text-muted">
                  signed up {new Date(user.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
