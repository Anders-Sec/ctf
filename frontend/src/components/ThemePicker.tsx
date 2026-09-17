import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { updateTheme } from "../api/auth";
import { useSession } from "../auth/session";
import { applyTheme, storeTheme } from "../theme/apply";
import { THEMES, type ThemeId } from "../theme/themes";

/**
 * The per-user theme picker (spec 048 §4).
 *
 * One control for everyone. The admin area gets the same presets as the player
 * area — colour is a working condition, and an admin at 11pm wants a dark
 * screen for the same reason a player does. What stays out of the admin area is
 * *word* theming: its labels and copy are practical (spec 049).
 */
export default function ThemePicker() {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  const choose = useMutation({
    mutationFn: (theme: ThemeId | null) => updateTheme(theme),
    // Painted before the request resolves. A theme switch that waits on a
    // round-trip feels broken, and the failure case is cheap: the session
    // refetch below puts back whatever the server actually holds.
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

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!me) return null;

  const current = me.theme;
  const following = me.theme_source === "event";

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Theme"
        title="Theme"
        className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-sunken"
      >
        Theme
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-64 rounded border border-border bg-surface-overlay p-1 shadow-lg"
        >
          {THEMES.map((theme) => {
            const selected = theme.id === current;
            return (
              <button
                key={theme.id}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                onClick={() => {
                  choose.mutate(theme.id);
                  setOpen(false);
                }}
                className={`block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-surface-sunken ${
                  selected ? "bg-surface-sunken" : ""
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">{theme.label}</span>
                  {/* A tick, not colour alone — the one control that must stay
                      legible while the reader is mid-way through changing how
                      everything looks. */}
                  {selected && <span aria-hidden>✓</span>}
                </span>
                <span className="block text-xs text-content-muted">{theme.description}</span>
              </button>
            );
          })}

          {/* Only offered once they have actually chosen something. Before that
              it would clear a preference that does not exist. */}
          {!following && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                choose.mutate(null);
                setOpen(false);
              }}
              className="mt-1 block w-full border-t border-border px-2 pb-1 pt-2 text-left text-xs text-content-muted hover:text-content"
            >
              Follow the event default
            </button>
          )}
          {following && (
            <p className="border-t border-border px-2 pb-1 pt-2 text-xs text-content-muted">
              Following the event default.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
