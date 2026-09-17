import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateHighContrast, updateTheme } from "../api/auth";
import { useSession } from "../auth/session";
import Spinner from "../components/Spinner";
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
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>

      <section className="mt-8">
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
    </main>
  );
}
