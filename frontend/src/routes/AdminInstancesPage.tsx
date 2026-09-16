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
  updateTemplate,
  type ContainerTemplate,
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

/**
 * A real template needs more than a name and an image. Until spec 046 these
 * fields existed on the API but not on this form, so every template took the
 * defaults — and `injects_answer` defaulting to true meant a static-flagged
 * container got a flag-shaped environment variable the platform would then
 * refuse, which is an hour of somebody's event spent chasing a decoy.
 */
const BLANK_TEMPLATE = {
  name: "",
  image: "",
  image_tag: "v1",
  container_port: 80,
  ttl_seconds: 3600,
  injects_answer: true,
  shared_instance: false,
  cpu_limit: "250m",
  memory_limit: "256Mi",
};

/**
 * A cleared number input reads as "", and `Number("")` is 0 — which for a
 * lifetime meant `expires_at = now`, and the expiry reconciler destroying a
 * team's container about a minute after they launched it. That happened at a
 * live event. Blank now falls back to the default instead of silently becoming
 * zero, and the server refuses out-of-range values regardless.
 */
const numberOr = (raw: string, fallback: number) => {
  const parsed = Number(raw);
  return raw.trim() === "" || Number.isNaN(parsed) ? fallback : parsed;
};

function Templates() {
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: ["admin", "templates"],
    queryFn: listTemplates,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...BLANK_TEMPLATE });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "templates"] });

  const create = useMutation({
    mutationFn: () => createTemplate(form),
    onSuccess: async () => {
      setForm({ ...BLANK_TEMPLATE });
      setOpen(false);
      await invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: invalidate,
  });
  const retime = useMutation({
    mutationFn: ({ id, ttl_seconds }: { id: string; ttl_seconds: number }) =>
      updateTemplate(id, { ttl_seconds }),
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
              min={1}
              max={65535}
              value={form.container_port}
              onChange={(e) =>
                setForm({
                  ...form,
                  container_port: numberOr(e.target.value, BLANK_TEMPLATE.container_port),
                })
              }
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Lifetime (seconds)
            <input
              type="number"
              min={60}
              max={86400}
              value={form.ttl_seconds}
              onChange={(e) =>
                setForm({
                  ...form,
                  ttl_seconds: numberOr(e.target.value, BLANK_TEMPLATE.ttl_seconds),
                })
              }
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
            <span className="mt-1 block text-xs text-muted">
              How long a launched container lives. At least 60 seconds — anything
              shorter is reaped before the team can use it.
            </span>
          </label>
          <label className="text-sm">
            CPU limit
            <input
              value={form.cpu_limit}
              onChange={(e) => setForm({ ...form, cpu_limit: e.target.value })}
              placeholder="250m"
              className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
            />
          </label>
          <label className="text-sm">
            Memory limit
            <input
              value={form.memory_limit}
              onChange={(e) => setForm({ ...form, memory_limit: e.target.value })}
              placeholder="256Mi"
              className="mt-1 w-full rounded border border-stone px-3 py-2 font-mono"
            />
          </label>
          <fieldset className="text-sm sm:col-span-2">
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={form.shared_instance}
                onChange={(e) =>
                  setForm({ ...form, shared_instance: e.target.checked })
                }
                className="mt-1"
              />
              <span>
                One container for every challenge on this template
                <span className="block text-xs text-muted">
                  For an image that carries several challenges. A party launches
                  it once and works all of them inside it.
                </span>
              </span>
            </label>
            <label className="mt-2 flex items-start gap-2">
              <input
                type="checkbox"
                checked={form.injects_answer}
                onChange={(e) =>
                  setForm({ ...form, injects_answer: e.target.checked })
                }
                className="mt-1"
              />
              <span>
                Mint a flag per team
                <span className="block text-xs text-muted">
                  Each challenge gets its own flag, unique to whoever launched
                  it, so a leaked flag is worthless to anyone else. Needs a
                  dynamic flag rule on each challenge.
                </span>
              </span>
            </label>
          </fieldset>
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
                {t.image}:{t.image_tag} · :{t.container_port} · {t.ttl_seconds}s ·{" "}
                {t.cpu_limit}/{t.memory_limit}
              </span>
              <span className="block text-xs text-muted">
                {t.shared_instance ? "shared container" : "one container per challenge"}
                {" · "}
                {t.injects_answer ? "flag minted per team" : "static flags"}
              </span>
            </span>
            <Lifetime template={t} onSave={(ttl) => retime.mutate({ id: t.id, ttl_seconds: ttl })} />
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

/**
 * Correcting a lifetime without deleting the template.
 *
 * A template created with a short lifetime expires a team's container almost as
 * soon as they launch it, and until this existed the only remedy was deleting
 * the template — which unbinds every challenge that used it, because the FK is
 * ON DELETE SET NULL. That happened at an event.
 */
function Lifetime({
  template,
  onSave,
}: {
  template: ContainerTemplate;
  onSave: (ttl: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(template.ttl_seconds));

  if (!editing) {
    return (
      <button
        onClick={() => {
          setValue(String(template.ttl_seconds));
          setEditing(true);
        }}
        className="text-xs underline text-muted"
      >
        Lifetime
      </button>
    );
  }

  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        min={60}
        max={86400}
        aria-label={`Lifetime for ${template.name}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-24 rounded border border-stone px-2 py-1 text-xs"
      />
      <button
        onClick={() => {
          onSave(numberOr(value, template.ttl_seconds));
          setEditing(false);
        }}
        className="text-xs underline"
      >
        Save
      </button>
      <button onClick={() => setEditing(false)} className="text-xs text-muted underline">
        Cancel
      </button>
    </span>
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
          {instance.template_name ? ` · ${instance.template_name}` : ""}
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
