import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateTheme } from "../api/auth";
import { useSession } from "../auth/session";
import { applyTheme, storeTheme } from "../theme/apply";
import { DARK_THEME, LIGHT_THEME, themeById } from "../theme/themes";

/**
 * The everyday light/dark control (spec 048 §10).
 *
 * A toggle rather than the picker it replaces. Four presets turned out to be
 * two — Torchlight read as Dark Dungeon two values apart — and a two-way choice
 * wants one click, not a menu to open and read. The accessibility switch and
 * any secret theme live on the settings page, which is where a thing you set
 * once belongs.
 */
export default function ThemeToggle() {
  const { me } = useSession();
  const queryClient = useQueryClient();

  const choose = useMutation({
    mutationFn: updateTheme,
    // Painted before the request resolves. A theme switch that waits on a
    // round-trip feels broken, and the failure case is cheap: the session
    // refetch puts back whatever the server actually holds.
    onMutate: (theme) => {
      if (theme) {
        applyTheme(theme);
        storeTheme(theme);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  if (!me) return null;

  // While high contrast is on it is serving the page, but the toggle still
  // reflects the choice underneath — that is what it would return them to.
  const dark = themeById(me.base_theme).mode === "dark";
  const next = dark ? LIGHT_THEME : DARK_THEME;

  return (
    <button
      type="button"
      onClick={() => choose.mutate(next)}
      // The label says what it will do, not what it currently is: a toggle
      // announcing its own state reads as a claim about the page.
      aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-sunken"
    >
      <span aria-hidden>{dark ? "☀" : "☾"}</span>
    </button>
  );
}
