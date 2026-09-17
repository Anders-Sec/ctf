import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEventConfig, updateEventConfig } from "../api/adminEvent";
import { updateTheme } from "../api/auth";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import { applyTheme, storeTheme } from "../theme/apply";
import { FALLBACK_THEME, SELECTABLE_THEMES, themeById, type ThemeId } from "../theme/themes";

/**
 * Theme settings (spec 048 §5).
 *
 * Two different things on one page, and keeping them distinct is the whole
 * design problem: the event default is what 200 people see, and the personal
 * choice is what this one admin sees. Setting one while looking at the other is
 * the mistake to design out, so each has its own section and its own wording.
 */
export default function AdminThemePage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();

  const config = useQuery({ queryKey: ["admin", "event-config"], queryFn: getEventConfig });

  const setDefault = useMutation({
    mutationFn: (theme: ThemeId | null) => updateEventConfig({ default_theme: theme }),
    onSuccess: async () => {
      // Moves this admin too, if they have not chosen for themselves.
      await queryClient.invalidateQueries({ queryKey: ["admin", "event-config"] });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const setMine = useMutation({
    mutationFn: (theme: ThemeId | null) => updateTheme(theme),
    onMutate: (theme) => {
      if (theme) {
        applyTheme(theme);
        storeTheme(theme);
      }
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  if (config.isPending) return <Spinner />;
  if (config.isError) return <ErrorMessage error={config.error} />;

  const eventDefault = config.data.default_theme;

  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Theme</h1>

      {!canWrite && (
        <p className="mt-4 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
          Read-only — only admins can change the event default.
        </p>
      )}

      <ErrorMessage error={setDefault.error ?? setMine.error} />

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Event default
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          What every player sees unless they pick something else. Changing it moves everyone who
          has not chosen; anyone who has is left alone.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {SELECTABLE_THEMES.map((theme) => {
            const selected =
              theme.id === eventDefault || (eventDefault === null && theme.id === FALLBACK_THEME);
            return (
              <button
                key={theme.id}
                type="button"
                disabled={!canWrite || setDefault.isPending}
                onClick={() => setDefault.mutate(theme.id)}
                aria-pressed={selected}
                className={`rounded border p-3 text-left disabled:opacity-60 ${
                  selected ? "border-accent bg-accent/10" : "border-border bg-surface-raised"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {theme.label}
                    {/* Marked, because an admin picking an event default should
                        know they are about to hand 200 people the gag theme. */}
                    {theme.secret && (
                      <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-[0.65rem] font-normal uppercase tracking-wide text-content-muted">
                        secret
                      </span>
                    )}
                  </span>
                  {selected && <span aria-hidden>✓</span>}
                </span>
                <span className="mt-1 block text-xs text-content-muted">{theme.description}</span>
              </button>
            );
          })}
        </div>

        {eventDefault === null && (
          <p className="mt-3 text-xs text-content-muted">
            No default is set, so the platform default ({themeById(FALLBACK_THEME).label}) applies.
          </p>
        )}
      </section>

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Your theme
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          Only affects this account. {me?.theme_source === "event"
            ? "You are currently following the event default."
            : `You have chosen ${themeById(me?.theme ?? FALLBACK_THEME).label}.`}
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          {SELECTABLE_THEMES.map((theme) => (
            <button
              key={theme.id}
              type="button"
              onClick={() => setMine.mutate(theme.id)}
              aria-pressed={me?.theme === theme.id && me?.theme_source === "user"}
              className={`rounded border px-3 py-1.5 text-sm ${
                me?.theme === theme.id ? "border-accent bg-accent/10" : "border-border"
              }`}
            >
              {theme.label}
            </button>
          ))}
          {me?.theme_source === "user" && (
            <button
              type="button"
              onClick={() => setMine.mutate(null)}
              className="rounded border border-border px-3 py-1.5 text-sm text-content-muted"
            >
              Follow the event default
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
