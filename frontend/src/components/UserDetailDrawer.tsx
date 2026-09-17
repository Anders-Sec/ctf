import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  approveUsers,
  disableUser,
  enableUser,
  getUser,
  resendMagicLink,
  setAssistantBlock,
  setUserRole,
} from "../api/admin";
import type { UserRole } from "../api/auth";
import { useSession } from "../auth/session";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";

/**
 * The per-player drawer (spec 052 §3).
 *
 * A drawer rather than an inline expander, for the reason spec 041 chose one
 * for challenges: the list does not move, so working through a queue does not
 * mean re-finding your place after every action.
 *
 * Deliberately no delete. An account with solves, audit entries and party
 * history cannot be removed without either destroying the record or leaving
 * dangling references. Disable is the operation that exists and it is the
 * correct one.
 */
export default function UserDetailDrawer({
  userId,
  onClose,
}: {
  userId: string;
  onClose: () => void;
}) {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const canWrite = me?.capabilities.administer ?? false;
  const [reason, setReason] = useState("");

  const detail = useQuery({
    queryKey: ["admin", "users", userId],
    queryFn: () => getUser(userId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    await queryClient.invalidateQueries({ queryKey: ["admin", "dashboard"] });
  };

  // Written out rather than built by a helper: a helper that calls useMutation
  // is a hook call inside a function, which is a rule violation waiting for the
  // day somebody makes one of these conditional.
  const approve = useMutation({
    mutationFn: (id: string) => approveUsers([id], reason || undefined),
    onSuccess: refresh,
  });
  const disable = useMutation({
    mutationFn: (id: string) => disableUser(id, reason),
    onSuccess: refresh,
  });
  const enable = useMutation({
    mutationFn: (id: string) => enableUser(id, reason),
    onSuccess: refresh,
  });
  const role = useMutation({
    mutationFn: (next: UserRole) => setUserRole(userId, next, reason || undefined),
    onSuccess: refresh,
  });
  const block = useMutation({
    mutationFn: (blocked: boolean) => setAssistantBlock(userId, blocked, reason || undefined),
    onSuccess: refresh,
  });
  const resend = useMutation({
    mutationFn: (id: string) => resendMagicLink(id),
    onSuccess: refresh,
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const error =
    detail.error ??
    approve.error ??
    disable.error ??
    enable.error ??
    role.error ??
    block.error ??
    resend.error;

  const data = detail.data;
  const user = data?.user;
  const isSelf = me?.user.id === userId;

  return (
    <>
      <div className="fixed inset-0 z-30 bg-content/30" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-label="User detail"
        className="fixed inset-y-0 right-0 z-40 w-full max-w-lg overflow-y-auto border-l border-border bg-surface-overlay p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{user?.display_name ?? "…"}</h2>
            {user && <p className="text-sm text-content-muted">{user.email}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-xl leading-none">
            ×
          </button>
        </div>

        <ErrorMessage error={error} />

        {!data || !user ? (
          <Spinner />
        ) : (
          <>
            <Section title="Identity">
              <Fact label="Source" value={user.source} />
              <Fact label="Role" value={user.role} />
              <Fact label="Status" value={user.status.replace("_", " ")} />
              {data.disabled_reason && <Fact label="Disabled because" value={data.disabled_reason} />}
              <Fact label="Joined" value={new Date(user.created_at).toLocaleString()} />
              <Fact
                label="Approved"
                value={
                  user.approved_at
                    ? `${new Date(user.approved_at).toLocaleString()}${
                        data.approved_by_name ? ` by ${data.approved_by_name}` : ""
                      }`
                    : "—"
                }
              />
              <Fact
                label="Last seen"
                value={user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "never"}
              />
            </Section>

            <Section title="Play">
              <Fact label="Solves" value={String(user.solve_count)} />
              <Fact label="XP" value={String(user.xp)} />
              <Fact label="Level" value={String(data.level)} />
              <Fact label="Class" value={data.class_name ?? "Classless"} />
              <Fact label="Hints used" value={String(data.hints_used)} />
              <Fact label="Achievements" value={String(data.achievement_count)} />
              {/* The single most useful field when someone is stuck. */}
              <Fact label="Current wall" value={data.current_wall ?? "—"} />
            </Section>

            <Section title="Parties">
              {data.parties.length === 0 ? (
                <p className="text-sm text-content-muted">Never joined one.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {data.parties.map((spell) => (
                    <li key={`${spell.team_id}-${spell.joined_at}`}>
                      {spell.team_name}{" "}
                      <span className="text-content-muted">
                        ({spell.role})
                        {spell.removed_at &&
                          ` · left ${new Date(spell.removed_at).toLocaleDateString()}${
                            spell.removal_reason ? ` (${spell.removal_reason})` : ""
                          }`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Recent activity">
              {data.recent_activity.length === 0 ? (
                <p className="text-sm text-content-muted">Nothing submitted yet.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {data.recent_activity.slice(0, 12).map((entry, index) => (
                    <li key={`${entry.challenge_id}-${index}`} className="flex gap-2">
                      <span className={entry.is_correct ? "text-success" : "text-content-muted"}>
                        {entry.is_correct ? "solved" : "tried"}
                      </span>
                      <span className="flex-1">{entry.challenge_title ?? "a deleted challenge"}</span>
                      <span className="text-content-faint">
                        {new Date(entry.created_at).toLocaleTimeString()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            {canWrite && (
              <Section title="Actions">
                <label className="block text-sm">
                  <span className="mb-1 block text-content-muted">
                    Reason (required to disable or enable)
                  </span>
                  <input
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1"
                  />
                </label>

                <div className="mt-3 flex flex-wrap gap-2">
                  {user.status === "pending_approval" && (
                    <Action onClick={() => approve.mutate(userId)}>Approve</Action>
                  )}
                  {user.status !== "disabled" && !isSelf && (
                    <Action
                      tone="danger"
                      disabled={reason.trim().length < 3}
                      onClick={() => disable.mutate(userId)}
                    >
                      Disable
                    </Action>
                  )}
                  {user.status === "disabled" && (
                    <Action
                      disabled={reason.trim().length < 3}
                      onClick={() => enable.mutate(userId)}
                    >
                      Re-enable
                    </Action>
                  )}
                  {user.source === "guest" && (
                    <Action onClick={() => resend.mutate(userId)}>Resend sign-in link</Action>
                  )}
                  <Action onClick={() => block.mutate(!data.assistant_blocked)}>
                    {data.assistant_blocked ? "Unblock System AI" : "Block System AI"}
                  </Action>
                </div>

                <label className="mt-3 block text-sm">
                  <span className="mb-1 block text-content-muted">Role</span>
                  <select
                    value={user.role}
                    disabled={isSelf}
                    onChange={(event) => role.mutate(event.target.value as UserRole)}
                    className="rounded border border-border-strong bg-surface-raised px-2 py-1"
                  >
                    <option value="player">player</option>
                    <option value="organizer">organizer</option>
                    <option value="admin">admin</option>
                  </select>
                  {isSelf && (
                    // There is one admin. Locking themselves out ends the event,
                    // and the server refuses it too.
                    <span className="ml-2 text-xs text-content-muted">
                      You cannot change your own role.
                    </span>
                  )}
                </label>

                <p className="mt-4 text-xs text-content-muted">
                  <Link
                    to={`/admin/audit?target_type=user&search=${encodeURIComponent(user.display_name)}`}
                    className="underline"
                  >
                    View this account&rsquo;s audit history
                  </Link>
                </p>
              </Section>
            )}
          </>
        )}
      </aside>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 border-t border-border pt-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <p className="flex gap-2 text-sm">
      <span className="w-32 shrink-0 text-content-muted">{label}</span>
      <span className="flex-1">{value}</span>
    </p>
  );
}

function Action({
  children,
  onClick,
  disabled,
  tone,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-3 py-1 text-sm disabled:opacity-40 ${
        tone === "danger" ? "border-danger text-danger" : "border-border"
      }`}
    >
      {children}
    </button>
  );
}
