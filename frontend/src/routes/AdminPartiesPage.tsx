import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { listParties, type PartySummary } from "../api/adminParties";
import ErrorMessage from "../components/ErrorMessage";
import PartyDetailDrawer from "../components/PartyDetailDrawer";
import Spinner from "../components/Spinner";

/**
 * Party administration (spec 053).
 *
 * Every team endpoint is player-scoped and gated on being the leader, which
 * works until the leader stops showing up. These are the fixes that were
 * two-minute jobs with a page and unanswerable without one.
 */
export default function AdminPartiesPage() {
  const [search, setSearch] = useState("");
  const [includeDisbanded, setIncludeDisbanded] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const parties = useQuery({
    queryKey: ["admin", "parties", { search, includeDisbanded }],
    queryFn: () => listParties({ search: search || undefined, include_disbanded: includeDisbanded }),
  });

  const refresh = useMutation({
    mutationFn: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "parties"] });
    },
  });

  return (
    <main className="p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Parties</h1>
        <p className="mt-2 text-sm text-content-muted">
          Moving somebody between parties moves their contribution with them — a party&rsquo;s
          standing is worked out from whoever is in it now.
        </p>
      </header>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name"
          aria-label="Search parties"
          className="rounded border border-border-strong bg-surface-raised px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeDisbanded}
            onChange={(event) => setIncludeDisbanded(event.target.checked)}
          />
          Show disbanded
        </label>
      </div>

      <ErrorMessage error={parties.error} />

      {parties.isPending ? (
        <Spinner label="Counting the parties…" />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-content-muted">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Name</th>
                <th className="py-2 pr-3 font-medium">Members</th>
                <th className="py-2 pr-3 font-medium">Leader</th>
                <th className="py-2 pr-3 font-medium">Visibility</th>
                <th className="py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {(parties.data ?? []).map((party) => (
                <Row key={party.team_id} party={party} onOpen={() => setOpenId(party.team_id)} />
              ))}
              {(parties.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-content-muted">
                    No parties match that.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {openId && (
        <PartyDetailDrawer
          teamId={openId}
          onClose={() => {
            setOpenId(null);
            refresh.mutate();
          }}
        />
      )}
    </main>
  );
}

function Row({ party, onOpen }: { party: PartySummary; onOpen: () => void }) {
  const full = party.member_count >= party.max_members;

  return (
    <tr className="border-b border-border">
      <td className="py-2 pr-3">
        <button type="button" onClick={onOpen} className="text-accent-strong underline">
          {party.name}
        </button>
        {party.disbanded_at && (
          <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-xs uppercase tracking-wide text-content-muted">
            disbanded
          </span>
        )}
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {/* Against the cap, so a full party reads as full. */}
        <span className={full ? "text-warning" : ""}>
          {party.member_count}/{party.max_members}
        </span>
      </td>
      <td className="py-2 pr-3">
        {party.leader_name ?? "—"}
        {party.leader_absent && !party.disbanded_at && (
          // Visible without opening anything: this party cannot accept anyone
          // or change anything until somebody else leads it.
          <span className="ml-2 text-xs text-warning">away</span>
        )}
      </td>
      <td className="py-2 pr-3 text-content-muted">
        {party.visibility}
        {party.has_password && <span className="ml-1 text-xs">· password</span>}
      </td>
      <td className="py-2 text-content-muted">
        {new Date(party.created_at).toLocaleDateString()}
      </td>
    </tr>
  );
}
