import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  addPartyMember,
  decideJoinRequest,
  disbandParty,
  getParty,
  listEligibleMembers,
  listParties,
  movePartyMember,
  removePartyMember,
  transferLeadership,
  updateParty,
} from "../api/adminParties";
import { useDialogFocus } from "../hooks/useDialogFocus";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";

/**
 * One party's drawer (spec 053 §3).
 *
 * The pending join requests come first on purpose: a leader who has gone home
 * leaves them stranded, and unsticking them is the single most likely reason to
 * open this at all.
 */
export default function PartyDetailDrawer({
  teamId,
  onClose,
}: {
  teamId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [confirmDisband, setConfirmDisband] = useState(false);

  const party = useQuery({ queryKey: ["admin", "parties", teamId], queryFn: () => getParty(teamId) });
  const eligible = useQuery({
    queryKey: ["admin", "parties", "eligible"],
    queryFn: listEligibleMembers,
  });
  const allParties = useQuery({ queryKey: ["admin", "parties", "all"], queryFn: () => listParties() });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "parties"] });
  };

  const rename = useMutation({
    mutationFn: (name: string) => updateParty(teamId, { name, reason: reason || undefined }),
    onSuccess: refresh,
  });
  const setCap = useMutation({
    mutationFn: (max_members: number) => updateParty(teamId, { max_members }),
    onSuccess: refresh,
  });
  const setVisibility = useMutation({
    mutationFn: (visibility: "public" | "private") => updateParty(teamId, { visibility }),
    onSuccess: refresh,
  });
  const clearPassword = useMutation({
    mutationFn: () => updateParty(teamId, { clear_join_password: true }),
    onSuccess: refresh,
  });
  const promote = useMutation({
    mutationFn: (userId: string) => transferLeadership(teamId, userId),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: (userId: string) => addPartyMember(teamId, userId, reason || undefined),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removePartyMember(teamId, userId),
    onSuccess: refresh,
  });
  const move = useMutation({
    mutationFn: ({ userId, to }: { userId: string; to: string }) =>
      movePartyMember(userId, to, reason || undefined),
    onSuccess: refresh,
  });
  const disband = useMutation({
    mutationFn: () => disbandParty(teamId, reason || undefined),
    onSuccess: async () => {
      await refresh();
      onClose();
    },
  });
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) =>
      decideJoinRequest(teamId, id, accept),
    onSuccess: refresh,
  });

  const panel = useRef<HTMLElement>(null);
  useDialogFocus(panel, { onClose });

  const data = party.data;
  const active = data?.members.filter((member) => member.removed_at === null) ?? [];
  const former = data?.members.filter((member) => member.removed_at !== null) ?? [];
  const elsewhere = (allParties.data ?? []).filter((row) => row.team_id !== teamId);

  const error =
    party.error ??
    rename.error ??
    setCap.error ??
    setVisibility.error ??
    promote.error ??
    add.error ??
    remove.error ??
    move.error ??
    disband.error ??
    decide.error;

  return (
    <>
      <div className="fixed inset-0 z-30 bg-content/30" onClick={onClose} aria-hidden />
      <aside
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Party detail"
        className="fixed inset-y-0 right-0 z-40 w-full max-w-xl overflow-y-auto border-l border-border bg-surface-overlay p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-xl font-semibold">{data?.name ?? "…"}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-xl leading-none">
            ×
          </button>
        </div>

        <ErrorMessage error={error} />

        {!data ? (
          <Spinner />
        ) : (
          <>
            {data.join_requests.length > 0 && (
              <Section title={`Waiting to join (${data.join_requests.length})`}>
                <ul className="flex flex-col gap-2">
                  {data.join_requests.map((request) => (
                    <li
                      key={request.id}
                      className="flex items-center gap-2 rounded border border-border px-2 py-1.5 text-sm"
                    >
                      <span className="flex-1">
                        {request.display_name}
                        {request.message && (
                          <span className="block text-xs text-content-muted">
                            &ldquo;{request.message}&rdquo;
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={() => decide.mutate({ id: request.id, accept: true })}
                        className="rounded border border-border px-2 py-0.5 text-xs"
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        onClick={() => decide.mutate({ id: request.id, accept: false })}
                        className="rounded border border-border px-2 py-0.5 text-xs text-content-muted"
                      >
                        Reject
                      </button>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            <Section title={`Members (${active.length}/${data.max_members})`}>
              <ul className="flex flex-col gap-2">
                {active.map((member) => (
                  <li key={member.user_id} className="rounded border border-border px-2 py-1.5 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="flex-1">
                        {member.display_name}
                        {member.user_id === data.leader_user_id && (
                          <span className="ml-2 text-xs uppercase tracking-wide text-accent-strong">
                            leader
                          </span>
                        )}
                        <span className="block text-xs text-content-muted">
                          {member.solve_count} solves · {member.xp} XP
                        </span>
                      </span>
                      {member.user_id !== data.leader_user_id && (
                        <>
                          <button
                            type="button"
                            onClick={() => promote.mutate(member.user_id)}
                            className="text-xs underline"
                          >
                            Make leader
                          </button>
                          <button
                            type="button"
                            onClick={() => remove.mutate(member.user_id)}
                            className="text-xs text-danger underline"
                          >
                            Remove
                          </button>
                        </>
                      )}
                    </div>

                    {member.user_id !== data.leader_user_id && elsewhere.length > 0 && (
                      <label className="mt-1 block text-xs text-content-muted">
                        Move to{" "}
                        <select
                          defaultValue=""
                          onChange={(event) => {
                            if (event.target.value) {
                              move.mutate({ userId: member.user_id, to: event.target.value });
                              event.target.value = "";
                            }
                          }}
                          aria-label={`Move ${member.display_name} to another party`}
                          className="rounded border border-border bg-surface-raised px-1 py-0.5"
                        >
                          <option value="">…</option>
                          {elsewhere.map((row) => (
                            <option key={row.team_id} value={row.team_id}>
                              {row.name} ({row.member_count}/{row.max_members})
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </li>
                ))}
              </ul>

              {active.length < data.max_members && (eligible.data ?? []).length > 0 && (
                <label className="mt-3 block text-sm">
                  <span className="mb-1 block text-content-muted">Add a party-less player</span>
                  <select
                    defaultValue=""
                    onChange={(event) => {
                      if (event.target.value) {
                        add.mutate(event.target.value);
                        event.target.value = "";
                      }
                    }}
                    className="rounded border border-border-strong bg-surface-raised px-2 py-1"
                  >
                    <option value="">Choose…</option>
                    {(eligible.data ?? []).map((row) => (
                      <option key={row.user_id} value={row.user_id}>
                        {row.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </Section>

            {former.length > 0 && (
              <Section title="Former members">
                {/* Never hard-deleted: the history is what an admin needs when
                    adjudicating a complaint about a kick. */}
                <ul className="flex flex-col gap-1 text-sm text-content-muted">
                  {former.map((member) => (
                    <li key={`${member.user_id}-${member.joined_at}`}>
                      {member.display_name} — left{" "}
                      {new Date(member.removed_at!).toLocaleDateString()}
                      {member.removal_reason && ` (${member.removal_reason})`}
                      {member.removed_by_name && ` · by ${member.removed_by_name}`}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            <Section title="Settings">
              <label className="block text-sm">
                <span className="mb-1 block text-content-muted">Reason (recorded in the log)</span>
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1"
                />
              </label>

              <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
                <label>
                  <span className="mb-1 block text-content-muted">Name</span>
                  <input
                    defaultValue={data.name}
                    onBlur={(event) => {
                      if (event.target.value !== data.name) rename.mutate(event.target.value);
                    }}
                    aria-label="Party name"
                    className="rounded border border-border-strong bg-surface-raised px-2 py-1"
                  />
                </label>

                <label>
                  <span className="mb-1 block text-content-muted">Max members</span>
                  <input
                    type="number"
                    min={active.length}
                    max={16}
                    defaultValue={data.max_members}
                    onBlur={(event) => {
                      const next = Number(event.target.value);
                      if (next && next !== data.max_members) setCap.mutate(next);
                    }}
                    aria-label="Max members"
                    className="w-20 rounded border border-border-strong bg-surface-raised px-2 py-1"
                  />
                </label>

                <label>
                  <span className="mb-1 block text-content-muted">Visibility</span>
                  <select
                    value={data.visibility}
                    onChange={(event) =>
                      setVisibility.mutate(event.target.value as "public" | "private")
                    }
                    aria-label="Visibility"
                    className="rounded border border-border-strong bg-surface-raised px-2 py-1"
                  >
                    <option value="public">public</option>
                    <option value="private">private</option>
                  </select>
                </label>

                {data.has_password && (
                  <button
                    type="button"
                    onClick={() => clearPassword.mutate()}
                    className="rounded border border-border px-2 py-1"
                  >
                    Clear join password
                  </button>
                )}
              </div>
              {data.has_password && (
                <p className="mt-1 text-xs text-content-muted">
                  The password cannot be shown — it is a hash. Clearing it turns the party into
                  request-to-join, which is the fix when nobody remembers it.
                </p>
              )}
            </Section>

            <Section title="Danger">
              {!data.disbanded_at ? (
                confirmDisband ? (
                  <div className="flex items-center gap-2 text-sm">
                    <span>Disband? Members become party-less; their solves are untouched.</span>
                    <button
                      type="button"
                      onClick={() => disband.mutate()}
                      className="rounded border border-danger px-2 py-1 text-danger"
                    >
                      Yes, disband
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDisband(false)}
                      className="text-content-muted underline"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmDisband(true)}
                    className="rounded border border-danger px-3 py-1 text-sm text-danger"
                  >
                    Disband party
                  </button>
                )
              ) : (
                <p className="text-sm text-content-muted">
                  Disbanded {new Date(data.disbanded_at).toLocaleString()}. Kept so the audit trail
                  still resolves.
                </p>
              )}

              <p className="mt-3 text-xs text-content-muted">
                <Link
                  to={`/admin/audit?target_type=team&search=${encodeURIComponent(data.name)}`}
                  className="underline"
                >
                  View this party&rsquo;s audit history
                </Link>
              </p>
            </Section>
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
