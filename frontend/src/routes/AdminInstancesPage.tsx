import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  forceTeardown,
  getAdminInstances,
  type AdminInstance,
} from "../api/adminInstances";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Everything running right now, for staff. The only action is teardown — the
 * lever for when a live target needs to stop immediately.
 *
 * Container *templates* used to share this route. They are a different job on a
 * different clock: templates are configuration, set up before the event and
 * rarely touched during it, while this page is opened in a hurry. Spec 049
 * split them so the page you reach for mid-event is not half filled with
 * things you are not looking for.
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
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "instances"] }),
  });

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Live dungeons</h1>
        <p className="mt-2 text-content-muted">
          Every challenge container running right now, with its owner. Tearing
          one down stops it immediately and is recorded in the audit log.
        </p>
      </header>

      {instances.isPending ? (
        <Spinner label="Counting the dungeons…" />
      ) : instances.isError ? (
        <ErrorMessage error={instances.error} />
      ) : instances.data.length === 0 ? (
        <p className="mt-8 text-content-muted">Nothing running.</p>
      ) : (
        <ul className="mt-6 space-y-3">
          {instances.data.map((instance) => (
            <Row
              key={instance.id}
              instance={instance}
              onTeardown={() => teardown.mutate(instance.id)}
            />
          ))}
        </ul>
      )}

    </main>
  );
}

function Row({
  instance,
  onTeardown,
}: {
  instance: AdminInstance;
  onTeardown: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface-raised p-4">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{instance.challenge_title}</p>
        <p className="text-sm text-content-muted">
          {instance.owner_label} · {instance.status}
          {instance.template_name ? ` · ${instance.template_name}` : ""}
          {instance.error ? ` · ${instance.error}` : ""}
        </p>
      </div>
      <span className="text-xs text-content-muted">
        expires {new Date(instance.expires_at).toLocaleTimeString()}
      </span>
      <button
        onClick={onTeardown}
        className="rounded border border-danger/50 px-3 py-1 text-sm text-danger"
      >
        Tear down
      </button>
    </li>
  );
}
