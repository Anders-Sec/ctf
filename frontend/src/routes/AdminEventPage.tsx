import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getEventConfig, updateEventConfig } from "../api/adminEvent";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Event settings — name, the start/end window, registration, and the System AI
 * switch. This is the gate that opens and closes the whole event, so it needs a
 * home; the backend has always supported it, there was just no page.
 *
 * Times are edited in the admin's local zone via datetime-local inputs and sent
 * as UTC ISO. The server clock is shown alongside, because that is the clock the
 * gates actually use.
 */
export default function AdminEventPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();
  const config = useQuery({
    queryKey: ["admin", "event-config"],
    queryFn: getEventConfig,
  });

  const [name, setName] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [registration, setRegistration] = useState(true);
  const [assistant, setAssistant] = useState(true);
  const [fog, setFog] = useState(true);

  useEffect(() => {
    if (config.data) {
      setName(config.data.name);
      setStarts(toLocalInput(config.data.starts_at));
      setEnds(toLocalInput(config.data.ends_at));
      setRegistration(config.data.registration_open);
      setAssistant(config.data.assistant_enabled);
      setFog(config.data.fog_of_war);
    }
  }, [config.data]);

  const save = useMutation({
    mutationFn: () =>
      updateEventConfig({
        name: name.trim(),
        starts_at: fromLocalInput(starts),
        ends_at: fromLocalInput(ends),
        registration_open: registration,
        assistant_enabled: assistant,
        fog_of_war: fog,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "event-config"] }),
  });

  if (config.isPending) return <Spinner />;
  if (config.isError) return <ErrorMessage error={config.error} />;

  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Event settings</h1>
      <p className="mt-2 text-sm text-muted">
        Server time is currently{" "}
        {new Date(config.data.server_time).toLocaleString()} — the clock the
        start and end gates use.
      </p>

      {!canWrite && (
        <p className="mt-4 rounded border border-stone bg-white/40 px-3 py-2 text-sm text-muted">
          Read-only — only admins can change event settings.
        </p>
      )}

      <form
        className="mt-6 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <label className="block text-sm">
          Event name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!canWrite}
            className="mt-1 w-full rounded border border-stone px-3 py-2"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            Starts
            <input
              type="datetime-local"
              value={starts}
              onChange={(e) => setStarts(e.target.value)}
              disabled={!canWrite}
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            Ends
            <input
              type="datetime-local"
              value={ends}
              onChange={(e) => setEnds(e.target.value)}
              disabled={!canWrite}
              className="mt-1 w-full rounded border border-stone px-3 py-2"
            />
          </label>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={registration}
            onChange={(e) => setRegistration(e.target.checked)}
            disabled={!canWrite}
          />
          Registration open (new guests can sign up)
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={assistant}
            onChange={(e) => setAssistant(e.target.checked)}
            disabled={!canWrite}
          />
          System AI enabled
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={fog}
            onChange={(e) => setFog(e.target.checked)}
            disabled={!canWrite}
          />
          Fog of war (dim locked zones on the map)
        </label>

        {canWrite && (
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded bg-ink px-4 py-2 text-sm text-parchment disabled:opacity-50"
            >
              Save
            </button>
            {save.isSuccess && (
              <span className="text-sm text-muted">Saved.</span>
            )}
          </div>
        )}
        <ErrorMessage error={save.error} />
      </form>
    </main>
  );
}

/** UTC ISO → the value a datetime-local input wants (local wall-clock, no zone). */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local (local wall-clock) → UTC ISO, or null when cleared. */
function fromLocalInput(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}
