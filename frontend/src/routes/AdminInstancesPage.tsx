import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { forceTeardown, getAdminInstances, type AdminInstance } from "../api/adminInstances";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Everything running, for staff. Fills the container panel spec 006's dashboard
 * left as a placeholder. The only action is teardown — the lever for when a live
 * target needs to stop now.
 */
export default function AdminInstancesPage() {
  const queryClient = useQueryClient();

  const instances = useQuery({
    queryKey: ["admin", "instances"],
    queryFn: getAdminInstances,
    refetchInterval: 10_000,
  });

  const teardown = useMutation({
    mutationFn: forceTeardown,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "instances"] }),
  });

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Live dungeons</h1>
        <p className="mt-2 text-muted">
          Every challenge container running right now, with its owner. Tearing one down stops it
          immediately and is recorded in the audit log.
        </p>
      </header>

      {instances.isPending ? (
        <Spinner label="Counting the dungeons…" />
      ) : instances.isError ? (
        <ErrorMessage error={instances.error} />
      ) : instances.data.length === 0 ? (
        <p className="mt-8 text-muted">Nothing running.</p>
      ) : (
        <ul className="mt-6 space-y-3">
          {instances.data.map((instance) => (
            <Row key={instance.id} instance={instance} onTeardown={() => teardown.mutate(instance.id)} />
          ))}
        </ul>
      )}
    </main>
  );
}

function Row({ instance, onTeardown }: { instance: AdminInstance; onTeardown: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-stone bg-white/40 p-4">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{instance.challenge_title}</p>
        <p className="text-sm text-muted">
          {instance.owner_label} · {instance.status}
          {instance.error ? ` · ${instance.error}` : ""}
        </p>
      </div>
      <span className="text-xs text-muted">expires {new Date(instance.expires_at).toLocaleTimeString()}</span>
      <button
        onClick={onTeardown}
        className="rounded border border-torch/50 px-3 py-1 text-sm text-torch"
      >
        Tear down
      </button>
    </li>
  );
}
