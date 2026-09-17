import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { getDashboard, type Dashboard } from "../api/adminOps";
import { useAdminView } from "../auth/adminView";

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
      { to: "/admin/scoreboard", label: "Scoreboard" },
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
  "/admin/announcements",
  "/admin/health",
  "/admin/export",
]);

/**
 * A thin colour flag per group, so the three sections can be told apart at a
 * glance rather than by reading their headings. Decoration only — the heading
 * text is always present, so nothing here is the sole carrier of meaning.
 */
const GROUP_ACCENT: Record<string, string> = {
  Operations: "bg-nav-operations",
  Content: "bg-nav-content",
  Settings: "bg-nav-settings",
};

const REFRESH_MS = 10_000;

export default function AdminLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const [, setAdminView] = useAdminView();

  // The same payload the dashboard already polls, so the badges cost nothing
  // beyond what the console was fetching anyway.
  const dashboard = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: getDashboard,
    refetchInterval: REFRESH_MS,
  });
  const counts = dashboard.data?.nav_counts;
  const event = dashboard.data?.event;

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
    <nav aria-label="Admin sections" className="flex h-full flex-col">
      {/* Only the list scrolls. The footer below is pinned to the viewport, not
          to the bottom of the document — on a long page (Skills, Challenges)
          that meant scrolling the whole event to get back to the player view. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {GROUPS.map((group, index) => (
          <div
            key={group.heading ?? `top-${index}`}
            // Groups are separated by space and a rule; items inside one are
            // not separated at all. Equal spacing everywhere was what made the
            // groups hard to pick out.
            className={group.heading ? "mt-4 border-t border-border pt-3 first:mt-0" : ""}
          >
            {group.heading && (
              <h2 className="mb-1 flex items-center gap-1.5 px-2 text-[0.65rem] font-bold uppercase tracking-[0.12em] text-content-muted">
                <span
                  aria-hidden
                  className={`h-2.5 w-0.5 rounded-full ${GROUP_ACCENT[group.heading] ?? "bg-border-strong"}`}
                />
                {group.heading}
              </h2>
            )}
            <ul className="flex flex-col gap-px">
              {group.items.map((item) => (
                <li key={item.to}>
                  <SidebarLink item={item} count={item.badge ? counts?.[item.badge] : undefined} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Standing context for every page above it, and the one cross-over
          control. Outside the scroll container, so it is always reachable. */}
      <div className="shrink-0 border-t border-border bg-surface-raised p-2">
        <EventClock event={event} />
        <button
          type="button"
          onClick={() => {
            setAdminView(false);
            navigate("/");
          }}
          className="mt-2 w-full rounded border border-border px-2 py-1 text-xs hover:bg-surface-sunken"
        >
          Player view
        </button>
      </div>
    </nav>
  );

  return (
    <div className="flex">
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        aria-expanded={drawerOpen}
        aria-controls="admin-sidebar"
        className="fixed bottom-4 left-4 z-30 rounded border border-border bg-surface-overlay px-3 py-2 text-sm shadow-lg lg:hidden"
      >
        Sections
      </button>

      {/* Sticky and a viewport tall, so navigation does not depend on where you
          are in the page. Desktop-first and unapologetically so: an event is not
          run from a phone. The drawer exists so a tablet is not locked out. */}
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 border-r border-border bg-surface-raised lg:block">
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
          "flex items-center justify-between gap-2 rounded px-2 py-1 text-[0.8125rem] leading-6",
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

/**
 * Whether the event is running, and the clock it is running against.
 *
 * Standing context for every page above it — "has the event started" changes
 * how you read the dashboard, the metrics and the challenge states — and it
 * costs nothing, because the dashboard payload is already being polled for the
 * badges.
 */
function EventClock({ event }: { event: Dashboard["event"] | undefined }) {
  if (!event) return null;

  return (
    <p className="px-2 text-xs text-content-muted">
      <span className="block truncate font-medium text-content">
        {event.name ?? "Unnamed event"}
      </span>
      <span className={event.running ? "text-success" : "text-content-muted"}>
        {event.running ? "running" : "not running"}
      </span>
      {" · "}
      {/* The server clock, because that is the one the gates use. */}
      <span className="tabular-nums">
        {new Date(event.server_time).toLocaleTimeString()}
      </span>
    </p>
  );
}
