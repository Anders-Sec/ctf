import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAdminView } from "../auth/adminView";
import { useSession } from "../auth/session";
import AssistantPanel from "./AssistantPanel";
import NotificationCentre from "./NotificationCentre";
import ProfileMenu from "./ProfileMenu";
import ThemeToggle from "./ThemeToggle";

/**
 * The player's navigation bar (spec 064).
 *
 * This file carried a note from spec 049 — *"the player nav is deliberately
 * untouched; its own pass belongs to the quality-of-life workstream"* — and this
 * is that pass.
 *
 * Three things moved. **The inbox went left**, so its panel opens into empty
 * space rather than over the assistant panel in the busy corner. **Sign out,
 * Settings and Admin view went behind the profile**, where a once-an-event
 * action belongs. **The content links collapse into a menu** below `md`, which
 * they previously did not do at all.
 */
export default function AppLayout() {
  const { me } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [adminView, setAdminView] = useAdminView();
  const [menuOpen, setMenuOpen] = useState(false);

  const isAdmin = Boolean(me?.capabilities.view_admin);
  // Only an admin can be in admin view; a stale flag for a demoted account
  // falls back to the player nav.
  const showingAdmin = isAdmin && adminView;

  const enterAdminView = () => {
    setAdminView(true);
    navigate("/admin");
  };

  // Following a link should not leave the menu hanging open behind the page it
  // just opened.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  const links = [
    me?.capabilities.play ? { to: "/challenges", label: "Challenges" } : null,
    me?.capabilities.view_scoreboard ? { to: "/scoreboard", label: "Scoreboard" } : null,
    { to: "/character", label: "Character" },
    { to: "/party", label: "Party" },
  ].filter((link): link is { to: string; label: string } => link !== null);

  return (
    <div className="min-h-screen">
      <nav className="relative border-b border-border bg-surface-raised">
        <div
          className={`flex items-center gap-3 p-4 ${
            // Full width in the admin area, where the content below is a
            // sidebar plus tables; a reading column for the player side.
            showingAdmin ? "" : "mx-auto max-w-5xl"
          }`}
        >
          <NavLink to={showingAdmin ? "/admin" : "/"} className="shrink-0 font-semibold">
            {/* The one piece of player-facing text that never got the dungeon
                treatment (spec 064 §7.2). */}
            {showingAdmin ? "CTF · Admin" : (me?.event?.name ?? "CTF")}
          </NavLink>

          {/*
           * Admin navigation is the grouped sidebar in AdminLayout (spec 049),
           * not a row of tabs here.
           */}
          {!showingAdmin && (
            <>
              {/* Left, so its panel opens into empty space rather than over the
                  assistant panel (spec 064 §2). */}
              {me?.capabilities.play && <NotificationCentre />}

              <div className="hidden items-center gap-4 md:flex">
                {links.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    // The tour points at these two by name (spec 066 §3.2).
                    data-tour={link.to === "/challenges" ? "board" : link.to === "/character" ? "character" : undefined}
                    className="text-sm hover:underline"
                  >
                    {link.label}
                  </NavLink>
                ))}
              </div>

              <button
                type="button"
                onClick={() => setMenuOpen((was) => !was)}
                aria-expanded={menuOpen}
                aria-label="Menu"
                className="text-sm md:hidden"
              >
                <span aria-hidden>☰</span>
              </button>
            </>
          )}

          <span className="ml-auto flex shrink-0 items-center gap-3">
            <ThemeToggle />
            {me && (
              // `!showingAdmin`: offering the way in while already inside would
              // be the confusing half of a toggle. The way back out is at the
              // foot of the admin sidebar (spec 049 §7).
              <ProfileMenu
                isAdmin={isAdmin && !showingAdmin}
                onEnterAdminView={enterAdminView}
              />
            )}
          </span>
        </div>

        {/* The content links, on a narrow window. The inbox, theme and profile
            stay on the bar — those are what you reach for without thinking. */}
        {menuOpen && !showingAdmin && (
          <div className="flex flex-col border-t border-border px-4 pb-3 md:hidden">
            {links.map((link) => (
              <NavLink key={link.to} to={link.to} className="py-2 text-sm">
                {link.label}
              </NavLink>
            ))}
          </div>
        )}
      </nav>
      <Outlet />
      <AssistantPanel />
    </div>
  );
}
