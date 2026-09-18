import { useState } from "react";

import type { ActivityItem } from "../api/scoreboard";

/**
 * The room, put back on the page (spec 069).
 *
 * An event where 200 people are playing at once otherwise looks, from any one
 * screen, like an event where nobody is.
 *
 * **It names the zone, not the challenge** — §3's decision, and the server
 * enforces it, so there is no title here to leak even by accident. Boss kills
 * are the exception and are named in full, because spec 032 already broadcasts
 * the first kill of each boss to everybody and being first is the whole point.
 *
 * Collapsible and remembered per browser. "I find this distracting" is what
 * collapsing is for, and it does not need a server-side preference (§7.2).
 */
const OPEN_KEY = "ctf.ticker.open";

const TIER_COLOUR: Record<string, string> = {
  neighborhood: "text-boss-neighborhood",
  borough: "text-boss-borough",
  city: "text-boss-city",
  province: "text-boss-province",
  country: "text-boss-country",
  floor: "text-boss-floor",
};

function storedOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) !== "0";
  } catch {
    return true;
  }
}

export default function ActivityTicker({ items }: { items: ActivityItem[] }) {
  const [open, setOpen] = useState(storedOpen);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(OPEN_KEY, next ? "1" : "0");
    } catch {
      // A collapse we cannot remember still collapses.
    }
  };

  return (
    <section className="mt-4 rounded border border-border bg-surface-raised">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
      >
        <span aria-hidden className="w-3 text-content-muted">
          {open ? "▾" : "▸"}
        </span>
        <span className="font-medium">In the dungeon</span>
        <span className="text-xs text-content-muted">
          {items.length === 0 ? "quiet" : "just now"}
        </span>
      </button>

      {open && (
        <ul
          aria-label="Recent activity"
          aria-live="polite"
          className="max-h-40 overflow-y-auto border-t border-border px-3 py-1.5"
        >
          {items.length === 0 ? (
            // Quiet, not nothing at all — so the space does not collapse.
            <li className="py-1 text-sm text-content-muted">
              The dungeon is quiet. Go and make some noise.
            </li>
          ) : (
            items.slice(0, 10).map((item, index) => (
              <li
                key={`${item.display_name}-${item.at}-${index}`}
                className="flex items-baseline gap-2 py-0.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{item.display_name}</span>{" "}
                  {item.kind === "boss" ? (
                    <>
                      felled{" "}
                      <span className={TIER_COLOUR[item.tier ?? ""] ?? "text-content"}>
                        {item.challenge_title}
                      </span>
                      <span aria-hidden> ☠</span>
                    </>
                  ) : (
                    <>
                      cleared something in{" "}
                      <span className="text-content-muted">{item.zone_name}</span>
                    </>
                  )}
                </span>
                <span className="shrink-0 text-xs text-content-faint">{ago(item.at)}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </section>
  );
}

/** Coarse: nobody needs seconds, and "just now" reads better than "0m ago". */
export function ago(at: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(at)) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
