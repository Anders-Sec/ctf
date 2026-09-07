import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  forceTeardown,
  getAdminInstances,
  type AdminInstance,
} from "../api/adminInstances";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
} from "../api/adminTemplates";
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
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "instances"] }),
  });

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Live dungeons</h1>
        <p className="mt-2 text-muted">
          Every challenge container running right now, with its owner. Tearing
          one down stops it immediately and is recorded in the audit log.
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
            <Row
              key={instance.id}
              instance={instance}
              onTeardown={() => teardown.mutate(instance.id)}
            />
          ))}
        </ul>
      )}

      <Templates />
    </main>
  );
}

function Templates() {
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: ["admin", "templates"],
    queryFn: listTemplates,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    image: "",
    image_tag: "v1",
    container_port: 80,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "templates"] });

  const create = useMutation({
    mutationFn: () => createTemplate(form),
    onSuccess: async () => {
      setForm({ name: "", image: "", image_tag: "v1", container_port: 80 });
      setOpen(false);
      await invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: invalidate,
  });

  return (
    <section className="mt-10">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-semibold">Container templates</h2>
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-sm underline"
        >
          {open ? "Cancel" : "New template"}
        </button>
      </div>
      <p className="mt-1 text-sm text-muted">
        The images challenges spin up. Assign one to a challenge from its
        editor.
      </p>

      {open && (
        <form
          className="mt-3 grid gap-2 rounded border border-stone bg-white/60 p-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label className="text-sm">
            Name
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Image
            <input
              required
              value={form.image}
              onChange={(e) => setForm({ ...form, image: e.target.value })}
              placeholder="ghcr.io/anders-sec/ctf-demo"
              className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
            />
          </label>
          <label className="text-sm">
            Tag
            <input
              value={form.image_tag}
              onChange={(e) => setForm({ ...form, image_tag: e.target.value })}
              className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
            />
          </label>
          <label className="text-sm">
            Container port
            <input
              type="number"
              value={form.container_port}
              onChange={(e) =>
                setForm({ ...form, container_port: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
            >
              Create template
            </button>
            <ErrorMessage error={create.error} />
          </div>
        </form>
      )}

      <ul className="mt-3 space-y-2">
        {(templates.data ?? []).map((t) => (
          <li
            key={t.id}
            className="flex items-center gap-3 rounded border border-stone bg-white/40 p-3 text-sm"
          >
            <span className="flex-1">
              <span className="font-medium">{t.name}</span>
              <span className="block font-mono text-xs text-muted">
                {t.image}:{t.image_tag} · :{t.container_port}
              </span>
            </span>
            <button
              onClick={() => remove.mutate(t.id)}
              className="text-xs text-torch underline"
            >
              Delete
            </button>
          </li>
        ))}
        {(templates.data ?? []).length === 0 && (
          <li className="text-sm text-muted">No templates yet.</li>
        )}
      </ul>
    </section>
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
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-stone bg-white/40 p-4">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{instance.challenge_title}</p>
        <p className="text-sm text-muted">
          {instance.owner_label} · {instance.status}
          {instance.error ? ` · ${instance.error}` : ""}
        </p>
      </div>
      <span className="text-xs text-muted">
        expires {new Date(instance.expires_at).toLocaleTimeString()}
      </span>
      <button
        onClick={onTeardown}
        className="rounded border border-torch/50 px-3 py-1 text-sm text-torch"
      >
        Tear down
      </button>
    </li>
  );
}
