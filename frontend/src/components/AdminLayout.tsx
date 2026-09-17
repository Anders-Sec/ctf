import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { getDashboard } from "../api/adminOps";

/**
 * The admin shell (spec 049).
 *
 * A persistent grouped sidebar, one level deep. The alternative sketched at the
 * start of Phase 3 was a row of group tabs each revealing its own sidebar —
 * two navigation steps to reach anything, which taxes exactly the move made
 * most under pressure: Reports to Signals to Instances and back, chasing one
 * problem. Group *headers* buy the same organisation for the price of a label
 * rather than a step.
 *
 * Names here are practical, never themed. "Live Instances" is faster to act on
 * than "Dungeons" when something is broken; the dungeon voice belongs to the
 * player-facing surfaces, where it lands harder for not being diluted across
 * the tooling.
 */

type BadgeKey = "open_reports" | "pending_approvals" | "open_signals" | "failed_instances";

interface Item {
  to: string;
  label: string;
  /** Match only this exact path, for a route that is a prefix of its siblings. */
  end?: boolean;
  badge?: BadgeKey;
}

interface Group {
  heading: string | null;
  items: Item[];
}

const GROUPS: Group[] = [
  { heading: null, items: [{ to: "/admin", label: "Dashboard", end: true }] },
  {
    heading: "Operations",
    items: [
      { to: "/admin/ops", label: "Reports & Adjustments", badge: "open_reports" },
      { to: "/admin/signals", label: "Anti-Cheat Signals", badge: "open_signals" },
      { to: "/admin/metrics", label: "Metrics" },
      { to: "/admin/assistant", label: "System AI" },
      { to: "/admin/instances", label: "Live Instances", badge: "failed_instances" },
      { to: "/admin/users", label: "Approvals", badge: "pending_approvals" },
      { to: "/admin/audit", label: "Audit Log" },
      { to: "/admin/announcements", label: "Announcements" },
      { to: "/admin/health", label: "Platform Health" },
    ],
  },
  {
    heading: "Content",
    items: [
      { to: "/admin/challenges", label: "Challenges" },
      { to: "/admin/skills", label: "Skills" },
      { to: "/admin/classes", label: "Classes" },
      { to: "/admin/achievements", label: "Achievements" },
      { to: "/admin/map", label: "Map" },
    ],
  },
  {
    heading: "Settings",
    items: [
      { to: "/admin/event", label: "Event" },
      { to: "/admin/theme", label: "Theme" },
      { to: "/admin/templates", label: "Container Templates" },
      { to: "/admin/email", label: "Email Delivery" },
      { to: "/admin/export", label: "Export" },
      { to: "/admin/data", label: "Data & Reset" },
    ],
  },
];

/**
 * Specced but not yet built. Listed here rather than hidden, because the
 * information architecture is the point of this spec — the shape of the admin
 * area should be visible now, so later specs drop into a settled structure
 * instead of renegotiating it one page at a time. Each renders a placeholder
 * naming its spec, so a click is answered rather than bounced.
 */
const NOT_YET_BUILT = new Set([
  "/admin/metrics",
  "/admin/audit",
  "/admin/announcements",
  "/admin/health",
  "/admin/email",
  "/admin/export",
]);

const REFRESH_MS = 10_000;

export default function AdminLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  // The same payload the dashboard already polls, so the badges cost nothing
  // beyond what the console was fetching anyway.
  const dashboard = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: getDashboard,
    refetchInterval: REFRESH_MS,
  });
  const counts = dashboard.data?.nav_counts;

  // Navigating is the signal that you are done with the menu.
  useEffect(() => setDrawerOpen(false), [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  const sidebar = (
    <nav aria-label="Admin sections" className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      {GROUPS.map((group, index) => (
        <div key={group.heading ?? `top-${index}`}>
          {group.heading && (
            <h2 className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-content-faint">
              {group.heading}
            </h2>
          )}
          <ul className="flex flex-col">
            {group.items.map((item) => (
              <li key={item.to}>
                <SidebarLink item={item} count={item.badge ? counts?.[item.badge] : undefined} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        aria-expanded={drawerOpen}
        aria-controls="admin-sidebar"
        className="fixed bottom-4 left-4 z-30 rounded border border-border bg-surface-overlay px-3 py-2 text-sm shadow-lg lg:hidden"
      >
        Sections
      </button>

      {/* Desktop-first and unapologetically so: an event is not run from a
          phone. The drawer exists so a tablet is not locked out. */}
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface-raised lg:block">
        {sidebar}
      </aside>

      {drawerOpen && (
        <>
          <div
            className="fixed inset-0 z-30 bg-content/40 lg:hidden"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <aside
            id="admin-sidebar"
            className="fixed inset-y-0 left-0 z-40 w-64 border-r border-border bg-surface-overlay shadow-xl lg:hidden"
          >
            {sidebar}
          </aside>
        </>
      )}

      <div className="min-w-0 flex-1">
        <Outlet />
      </div>
    </div>
  );
}

function SidebarLink({ item, count }: { item: Item; count: number | undefined }) {
  const unbuilt = NOT_YET_BUILT.has(item.to);

  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        [
          "flex items-center justify-between gap-2 rounded px-2 py-1.5 text-sm",
          // Marked by fill and a left rule, never by colour alone.
          isActive
            ? "border-l-2 border-accent bg-surface-sunken font-medium"
            : "border-l-2 border-transparent hover:bg-surface-sunken",
          unbuilt ? "text-content-faint" : "",
        ].join(" ")
      }
    >
      <span>{item.label}</span>
      {/* Only when non-zero. A zero badge is noise that teaches you to stop
          reading badges. */}
      {count !== undefined && count > 0 && (
        <span
          className="rounded-full bg-accent px-1.5 text-xs font-semibold text-accent-content tabular-nums"
          aria-label={`${count} waiting`}
        >
          {count}
        </span>
      )}
    </NavLink>
  );
}
