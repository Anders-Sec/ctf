import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  updateDisplayName,
  updateHighContrast,
  updateMutedKinds,
  updateTheme,
} from "../api/auth";
import { useSession } from "../auth/session";
import AvatarEditor from "../components/AvatarEditor";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";
import { KINDS_IN, metaFor } from "../components/notificationKinds";
import { openTour } from "../components/Tour";
import { applyTheme, storeTheme } from "../theme/apply";
import {
  GRANTABLE_THEMES,
  HIGH_CONTRAST_THEME,
  TOGGLE_THEMES,
  themeById,
  type ThemeId,
} from "../theme/themes";

/**
 * Player settings (spec 048 §10.3).
 *
 * Appearance, and the accessibility switch that did not belong in a list of
 * looks. A secret theme appears here only once the player holds one, which
 * spec 058 §5 settled: an achievement hands it over, or an admin does. The
 * section is absent until they hold one, so it is a discovery rather than a
 * list of things they cannot have.
 */
export default function SettingsPage() {
  const { me } = useSession();
  const queryClient = useQueryClient();

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["me"] });

  const setTheme = useMutation({
    mutationFn: (theme: ThemeId) => updateTheme(theme),
    onMutate: (theme) => {
      // Only paint immediately when high contrast is not overriding — otherwise
      // the page would flash a theme the player is not going to be left on.
      if (!me?.high_contrast) {
        applyTheme(theme);
        storeTheme(theme);
      }
    },
    onSettled: refresh,
  });

  const rename = useMutation({
    mutationFn: (value: string) => updateDisplayName(value),
    onSuccess: refresh,
  });

  const mute = useMutation({
    mutationFn: (kinds: string[]) => updateMutedKinds(kinds),
    onSuccess: refresh,
  });

  const setHighContrast = useMutation({
    mutationFn: (on: boolean) => updateHighContrast(on),
    onMutate: (on) => {
      const next = on ? HIGH_CONTRAST_THEME : (me?.base_theme ?? "parchment");
      applyTheme(next);
      storeTheme(next);
    },
    onSettled: refresh,
  });

  if (!me) return <Spinner />;

  const base = me.base_theme;
  // Held, not merely worn: the server sends the unlock rows, so a player who
  // earned a theme and then toggled back to daylight can still find it.
  const held = GRANTABLE_THEMES.filter((theme) => me.unlocked_themes.includes(theme.id));

  return (
    // Wider than it was: the avatar editor needs a preview beside its catalogue
    // and 2xl put them on top of each other on a laptop.
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Your likeness
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          Everyone starts with a crest drawn from their name. What you earn goes
          on top of it.
        </p>
        <div className="mt-3">
          <AvatarEditor />
        </div>
      </section>

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Appearance
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {TOGGLE_THEMES.map((theme) => (
            <button
              key={theme.id}
              type="button"
              onClick={() => setTheme.mutate(theme.id)}
              aria-pressed={base === theme.id}
              className={`rounded border px-3 py-1.5 text-sm ${
                base === theme.id ? "border-accent bg-accent/10 font-medium" : "border-border"
              }`}
            >
              {theme.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-content-muted">{themeById(base).description}</p>

        {held.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-medium">Found</h3>
            <p className="mt-1 text-xs text-content-muted">
              {held.length === 1 ? "A theme you" : "Themes you"} unearthed. Nobody
              was ever told these were here.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {held.map((theme) => (
                <button
                  key={theme.id}
                  type="button"
                  onClick={() => setTheme.mutate(theme.id)}
                  aria-pressed={base === theme.id}
                  className={`rounded border px-3 py-1.5 text-left text-sm ${
                    base === theme.id
                      ? "border-accent bg-accent/10 font-medium"
                      : "border-border"
                  }`}
                >
                  {theme.label}
                  <span className="mt-0.5 block text-xs font-normal text-content-muted">
                    {theme.description}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Accessibility
        </h2>

        <label className="mt-3 flex items-start gap-3">
          <input
            type="checkbox"
            checked={me.high_contrast}
            onChange={(event) => setHighContrast.mutate(event.target.checked)}
            className="mt-1"
          />
          <span className="text-sm">
            <span className="font-medium">High contrast</span>
            <span className="mt-1 block text-content-muted">
              Maximum separation, heavy borders and no translucency. Overrides the appearance
              choice above while it is on; turning it off puts back{" "}
              {themeById(base).label}.
            </span>
          </span>
        </label>
      </section>

      <NameSection
        canRename={me.can_rename}
        current={me.user.display_name}
        pending={rename.isPending}
        error={rename.error}
        onSave={(value) => rename.mutate(value)}
      />

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Notifications
        </h2>
        <p className="mt-1 text-xs text-content-muted">
          A muted kind still arrives and still sits in your inbox — it just stops
          popping up and stops counting on the badge.
        </p>

        {/* Built from KIND_META, so a tenth kind appears here without this page
            being touched (spec 070 §4). */}
        {(["yours", "event"] as const).map((tab) => (
          <div key={tab} className="mt-3">
            <h3 className="text-xs font-medium uppercase tracking-wide text-content-faint">
              {tab === "yours" ? "Yours" : "Event"}
            </h3>
            <ul className="mt-1 flex flex-col gap-1">
              {KINDS_IN[tab].map((kind) => {
                const muted = me.muted_notification_kinds.includes(kind);
                return (
                  <li key={kind}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={!muted}
                        disabled={mute.isPending}
                        onChange={() =>
                          mute.mutate(
                            muted
                              ? me.muted_notification_kinds.filter((k) => k !== kind)
                              : [...me.muted_notification_kinds, kind],
                          )
                        }
                      />
                      {metaFor(kind).label}
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
        <ErrorMessage error={mute.error} />
      </section>

      <section className="mt-10 border-t border-border pt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Getting started
        </h2>
        <p className="mt-1 text-sm text-content-muted">
          The four-stop tour of the dungeon, if you skipped it or want it again.
        </p>
        <button type="button" onClick={openTour} className="mt-2 text-sm underline">
          Show the tour
        </button>
      </section>
    </main>
  );
}

/**
 * Your name — offered only to the accounts that can keep one (spec 070 §3).
 *
 * `identity.py` rewrites `display_name` from the corporate profile on **every**
 * sign-in, so an Entra account that renamed itself here would be told it saved
 * and then quietly reverted. Saying so is better than offering it.
 */
function NameSection({
  canRename,
  current,
  pending,
  error,
  onSave,
}: {
  canRename: boolean;
  current: string;
  pending: boolean;
  error: unknown;
  onSave: (value: string) => void;
}) {
  const [name, setName] = useState(current);

  return (
    <section className="mt-10 border-t border-border pt-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
        Your name
      </h2>

      {!canRename ? (
        <p className="mt-2 text-sm text-content-muted">
          Your name comes from your work account, and changing it here would not
          stick — it is refreshed every time you sign in. You appear as{" "}
          <span className="font-medium text-content">{current}</span>.
        </p>
      ) : (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) onSave(name.trim());
          }}
        >
          <label className="flex-1 text-sm">
            <span className="mb-1 block text-content-muted">
              What everybody else sees
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-label="Display name"
              className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1.5"
            />
          </label>
          <button
            type="submit"
            disabled={pending || !name.trim() || name.trim() === current}
            className="rounded bg-accent-strong px-3 py-1.5 text-sm font-medium text-accent-content disabled:opacity-50"
          >
            {pending ? "Saving…" : "Save"}
          </button>
          <ErrorMessage error={error} />
        </form>
      )}
    </section>
  );
}
