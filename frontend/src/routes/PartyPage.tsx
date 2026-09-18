import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  acceptJoinRequest,
  createTeam,
  getTeam,
  joinTeam,
  leaveTeam,
  listJoinRequests,
  listTeams,
  rejectJoinRequest,
  requestToJoin,
  transferLeadership,
  updateTeam,
  type TeamVisibility,
} from "../api/teams";
import { getPartyPanel } from "../api/scoreboard";
import { useSession } from "../auth/session";
import Avatar from "../components/Avatar";
import BossStars from "../components/BossStars";
import ErrorMessage from "../components/ErrorMessage";
import PartyCoverage from "../components/PartyCoverage";
import Spinner from "../components/Spinner";

export default function PartyPage() {
  const { me } = useSession();
  if (!me) return <Spinner />;

  return (
    <main className="mx-auto max-w-3xl p-6">
      {me.team ? <MyParty teamId={me.team.id} /> : <PartyBrowser />}
    </main>
  );
}

/* ------------------------------------------------------------------ */
/* Browsing and forming a party                                        */
/* ------------------------------------------------------------------ */

function PartyBrowser() {
  const queryClient = useQueryClient();
  const { refresh } = useSession();
  const [tab, setTab] = useState<"join" | "create">("join");

  const teams = useQuery({ queryKey: ["teams"], queryFn: listTeams });

  const afterChange = async () => {
    await refresh();
    await queryClient.invalidateQueries({ queryKey: ["teams"] });
  };

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Find your party</h1>
        <p className="mt-2 text-content-muted">
          Adventure alone if you must, but parties of up to eight fare better.
        </p>
      </header>

      <div className="flex gap-2" role="tablist">
        {(["join", "create"] as const).map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={`rounded px-4 py-2 text-sm font-medium ${
              tab === value ? "bg-content text-surface" : "border border-border"
            }`}
          >
            {value === "join" ? "Join a party" : "Start a party"}
          </button>
        ))}
      </div>

      {tab === "create" ? (
        <CreatePartyForm onCreated={afterChange} />
      ) : teams.isPending ? (
        <Spinner label="Looking for parties…" />
      ) : (
        <PartyList teams={teams.data ?? []} onJoined={afterChange} />
      )}
    </div>
  );
}

function PartyList({
  teams,
  onJoined,
}: {
  teams: Awaited<ReturnType<typeof listTeams>>;
  onJoined: () => Promise<void>;
}) {
  if (teams.length === 0) {
    return <p className="text-content-muted">No open parties yet. Start the first one.</p>;
  }

  return (
    <ul className="flex flex-col gap-3">
      {teams.map((team) => (
        <PartyRow key={team.id} team={team} onJoined={onJoined} />
      ))}
    </ul>
  );
}

function PartyRow({
  team,
  onJoined,
}: {
  team: Awaited<ReturnType<typeof listTeams>>[number];
  onJoined: () => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [asking, setAsking] = useState(false);

  const join = useMutation({
    mutationFn: () => joinTeam(team.id, password || undefined),
    onSuccess: onJoined,
  });
  // The message was dead until spec 072: the leader's view has always rendered
  // it, the API has always accepted it, and nothing ever sent one — so every
  // request arrived as a bare name to approve or decline.
  const askToJoin = useMutation({
    mutationFn: () => requestToJoin(team.id, message.trim() || undefined),
  });

  return (
    <li className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-medium">{team.name}</p>
          <p className="text-sm text-content-muted">
            {team.member_count} / {team.max_members} adventurers
            {team.visibility === "private" && " · private"}
          </p>
        </div>

        {!team.has_space ? (
          <span className="text-sm text-content-muted">Full</span>
        ) : team.requires_password && !showPassword ? (
          <button
            onClick={() => setShowPassword(true)}
            className="rounded border border-content px-3 py-1.5 text-sm"
          >
            Join with password
          </button>
        ) : team.visibility === "private" && !team.requires_password ? (
          <button
            onClick={() => (asking ? askToJoin.mutate() : setAsking(true))}
            disabled={askToJoin.isPending || askToJoin.isSuccess}
            className="rounded border border-content px-3 py-1.5 text-sm disabled:opacity-50"
          >
            {askToJoin.isSuccess ? "Request sent" : asking ? "Send request" : "Ask to join"}
          </button>
        ) : !team.requires_password ? (
          <button
            onClick={() => join.mutate()}
            disabled={join.isPending}
            className="rounded bg-content px-3 py-1.5 text-sm text-surface disabled:opacity-50"
          >
            Join
          </button>
        ) : null}
      </div>

      {asking && !askToJoin.isSuccess && (
        <div className="mt-3">
          <label htmlFor={`ask-${team.id}`} className="block text-sm">
            Say something? <span className="text-content-muted">(optional)</span>
          </label>
          <textarea
            id={`ask-${team.id}`}
            rows={2}
            maxLength={280}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Who you are, or why you want in."
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
      )}

      {showPassword && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            join.mutate();
          }}
        >
          <input
            type="password"
            aria-label={`Password for ${team.name}`}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="flex-1 rounded border border-border px-3 py-1.5 text-sm"
            placeholder="Party password"
          />
          <button
            type="submit"
            disabled={join.isPending}
            className="rounded bg-content px-3 py-1.5 text-sm text-surface disabled:opacity-50"
          >
            Join
          </button>
        </form>
      )}

      <ErrorMessage error={join.error ?? askToJoin.error} />
    </li>
  );
}

function CreatePartyForm({ onCreated }: { onCreated: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState<TeamVisibility>("public");
  const [password, setPassword] = useState("");

  const create = useMutation({
    mutationFn: () =>
      createTeam({
        name: name.trim(),
        visibility,
        join_password: visibility === "private" && password ? password : null,
      }),
    onSuccess: onCreated,
  });

  return (
    <form
      className="rounded-lg border border-border bg-surface-raised p-6"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <label htmlFor="party-name" className="block text-sm">
        Party name
      </label>
      <input
        id="party-name"
        required
        minLength={3}
        maxLength={32}
        value={name}
        onChange={(event) => setName(event.target.value)}
        className="mt-1 w-full rounded border border-border px-3 py-2"
      />

      <fieldset className="mt-4">
        <legend className="text-sm">Who can join?</legend>
        {(
          [
            ["public", "Anyone can join"],
            ["private", "Only with a password, or my approval"],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="mt-2 flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="visibility"
              value={value}
              checked={visibility === value}
              onChange={() => setVisibility(value)}
            />
            {label}
          </label>
        ))}
      </fieldset>

      {visibility === "private" && (
        <div className="mt-4">
          <label htmlFor="party-password" className="block text-sm">
            Party password <span className="text-content-muted">(optional)</span>
          </label>
          <input
            id="party-password"
            type="password"
            minLength={6}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2"
          />
          <p className="mt-1 text-xs text-content-muted">
            Leave it blank and people will have to ask you to let them in.
          </p>
        </div>
      )}

      <button
        type="submit"
        disabled={create.isPending || name.trim().length < 3}
        className="mt-5 w-full rounded bg-content px-4 py-2 font-medium text-surface disabled:opacity-50"
      >
        {create.isPending ? "Gathering…" : "Form the party"}
      </button>
      <ErrorMessage error={create.error} />
    </form>
  );
}

/* ------------------------------------------------------------------ */
/* Your own party                                                      */
/* ------------------------------------------------------------------ */

function MyParty({ teamId }: { teamId: string }) {
  const { me, refresh } = useSession();
  const queryClient = useQueryClient();

  const team = useQuery({ queryKey: ["team", teamId], queryFn: () => getTeam(teamId) });
  // Spec 059 built this and nothing rendered it for your own party.
  const panel = useQuery({
    queryKey: ["scoreboard", "party", teamId],
    queryFn: () => getPartyPanel(teamId),
  });
  const isLeader = me?.team?.is_leader ?? false;

  const requests = useQuery({
    queryKey: ["team", teamId, "join-requests"],
    queryFn: () => listJoinRequests(teamId),
    enabled: isLeader,
  });

  const reload = async () => {
    await refresh();
    await queryClient.invalidateQueries({ queryKey: ["team", teamId] });
  };

  const leave = useMutation({
    mutationFn: () => leaveTeam(teamId, me!.user.id),
    onSuccess: reload,
  });
  const kick = useMutation({
    mutationFn: (userId: string) => leaveTeam(teamId, userId),
    onSuccess: reload,
  });
  const promote = useMutation({
    mutationFn: (userId: string) => transferLeadership(teamId, userId),
    onSuccess: reload,
  });
  const accept = useMutation({
    mutationFn: (requestId: string) => acceptJoinRequest(teamId, requestId),
    onSuccess: reload,
  });
  const reject = useMutation({
    mutationFn: (requestId: string) => rejectJoinRequest(teamId, requestId),
    onSuccess: reload,
  });

  if (team.isPending) return <Spinner label="Mustering the party…" />;
  if (team.isError || !team.data) return <ErrorMessage error={team.error} />;

  const detail = team.data;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold tracking-tight">{detail.name}</h1>
          <p className="mt-1 text-content-muted">
            {detail.member_count} / {detail.max_members} adventurers ·{" "}
            {detail.visibility === "private" ? "private" : "open to all"}
          </p>
        </div>
        <button
          onClick={() => leave.mutate()}
          disabled={leave.isPending}
          className="shrink-0 rounded border border-border px-3 py-1.5 text-sm hover:border-accent"
        >
          Leave party
        </button>
      </header>

      {/* The standing this page has never shown. Until spec 067 a player could
          learn more about a stranger's party from the scoreboard than about
          their own party from here. */}
      {panel.data && (
        <section className="rounded-lg border border-border-strong bg-surface-raised p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex items-center gap-3">
              <span className="text-2xl font-semibold tabular-nums">
                #{panel.data.rank}
              </span>
              <span className="text-sm text-content-muted">
                Level {panel.data.level}
              </span>
            </span>
            <BossStars stars={panel.data.stars} size="lg" />
          </div>
          <p className="mt-2 text-sm text-content-muted tabular-nums">
            {panel.data.solve_count} solved · {panel.data.achievement_count} awards ·
            founded {new Date(panel.data.founded_at).toLocaleDateString()}
          </p>
        </section>
      )}

      <PartyCoverage teamId={teamId} />

      <p className="rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
        Your solves are your own — if you leave, your XP goes with you.
      </p>

      <ErrorMessage error={leave.error ?? kick.error ?? promote.error} />

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">Roster</h2>
        <ul className="mt-3 flex flex-col gap-2">
          {detail.members.map((member) => (
            <li
              key={member.user_id}
              className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised p-3"
            >
              <Avatar
                userId={member.user_id}
                displayName={member.display_name}
              />
              <span className="flex-1">
                {member.display_name}
                {member.is_leader && (
                  <span className="ml-2 rounded bg-surface-sunken px-2 py-0.5 text-xs">Leader</span>
                )}
                {member.user_id === me?.user.id && (
                  <span className="ml-2 text-xs text-content-muted">you</span>
                )}
              </span>

              {isLeader && !member.is_leader && (
                <span className="flex gap-2">
                  <button
                    onClick={() => promote.mutate(member.user_id)}
                    className="rounded border border-border px-2 py-1 text-xs"
                  >
                    Make leader
                  </button>
                  <button
                    onClick={() => kick.mutate(member.user_id)}
                    className="rounded border border-accent/60 px-2 py-1 text-xs text-accent-strong"
                  >
                    Remove
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {isLeader && (
        <>
          <JoinRequestsSection
            requests={requests.data ?? []}
            onAccept={(id) => accept.mutate(id)}
            onReject={(id) => reject.mutate(id)}
            error={accept.error ?? reject.error}
          />
          <PartySettings team={detail} onSaved={reload} />
        </>
      )}
    </div>
  );
}

function JoinRequestsSection({
  requests,
  onAccept,
  onReject,
  error,
}: {
  requests: Awaited<ReturnType<typeof listJoinRequests>>;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  error: unknown;
}) {
  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
        Knocking at the door ({requests.length})
      </h2>
      <ErrorMessage error={error} />
      {requests.length === 0 ? (
        <p className="mt-2 text-sm text-content-muted">Nobody is waiting.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {requests.map((request) => (
            <li
              key={request.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised p-3"
            >
              <span className="flex-1">
                {request.display_name}
                {request.message && (
                  <span className="block text-sm text-content-muted">“{request.message}”</span>
                )}
              </span>
              <button
                onClick={() => onAccept(request.id)}
                className="rounded bg-content px-3 py-1 text-xs text-surface"
              >
                Let them in
              </button>
              <button
                onClick={() => onReject(request.id)}
                className="rounded border border-border px-3 py-1 text-xs"
              >
                Decline
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PartySettings({
  team,
  onSaved,
}: {
  team: Awaited<ReturnType<typeof getTeam>>;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(team.name);
  const [visibility, setVisibility] = useState<TeamVisibility>(team.visibility);
  const [password, setPassword] = useState("");
  const [clearPassword, setClearPassword] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      updateTeam(team.id, {
        // Unchanged fields go as `undefined` rather than as their current
        // value: the endpoint patches what it is given.
        name: name.trim() === team.name ? undefined : name.trim(),
        visibility: visibility === team.visibility ? undefined : visibility,
        join_password: password ? password : undefined,
        clear_password: clearPassword || undefined,
      }),
    onSuccess: async () => {
      setPassword("");
      setClearPassword(false);
      await onSaved();
    },
  });

  return (
    <section className="rounded-lg border border-border bg-surface-raised p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">Party settings</h2>
      <form
        className="mt-3 flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label className="text-sm">
          Name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2"
          />
        </label>

        <label className="text-sm">
          Visibility
          <select
            value={visibility}
            onChange={(event) => setVisibility(event.target.value as TeamVisibility)}
            className="mt-1 w-full rounded border border-border px-3 py-2"
          >
            <option value="public">Open to all</option>
            <option value="private">Private</option>
          </select>
        </label>

        {visibility === "private" && (
          <label className="text-sm">
            {team.requires_password ? "Change password" : "Set a password"}
            <input
              type="password"
              minLength={6}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={clearPassword}
              className="mt-1 w-full rounded border border-border px-3 py-2 disabled:opacity-50"
              placeholder="Leave blank to keep approving requests yourself"
            />
          </label>
        )}

        {/* `clear_password` was implemented all the way down and sent by
            nothing (spec 072 §3.2). Without it a leader who sets a password is
            stuck with one until they go public and back. */}
        {visibility === "private" && team.requires_password && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={clearPassword}
              onChange={(event) => {
                setClearPassword(event.target.checked);
                if (event.target.checked) setPassword("");
              }}
            />
            Remove the password and approve requests myself
          </label>
        )}

        <button
          type="submit"
          disabled={save.isPending}
          className="self-start rounded bg-content px-4 py-2 text-sm text-surface disabled:opacity-50"
        >
          Save changes
        </button>
        <ErrorMessage error={save.error} />
      </form>
    </section>
  );
}
