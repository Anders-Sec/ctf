import { useMutation } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { logout } from "../api/auth";
import { useAdminView } from "../auth/adminView";
import { useSession } from "../auth/session";
import AssistantPanel from "./AssistantPanel";
import Avatar from "./Avatar";
import NotificationCentre from "./NotificationCentre";
import ThemePicker from "./ThemePicker";

export default function AppLayout() {
  const { me } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [adminView, setAdminView] = useAdminView();

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      // Clear everything: another player may sign in on this browser next.
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });

  const isAdmin = Boolean(me?.capabilities.view_admin);
  // Only an admin can be in admin view; a stale flag for a demoted account
  // falls back to the player nav.
  const showingAdmin = isAdmin && adminView;

  const enterAdminView = () => {
    setAdminView(true);
    navigate("/admin");
  };

  return (
    <div className="min-h-screen">
      <nav className="relative border-b border-border bg-surface-raised">
        <div
          className={`flex items-center gap-4 p-4 ${
            // Full width in the admin area, where the content below is a
            // sidebar plus tables; a reading column for the player side.
            showingAdmin ? "" : "mx-auto max-w-3xl"
          }`}
        >
          <NavLink to={showingAdmin ? "/admin" : "/"} className="font-semibold">
            {showingAdmin ? "CTF · Admin" : "CTF"}
          </NavLink>

          {/*
           * Admin navigation is the grouped sidebar in AdminLayout (spec 049),
           * not a row of tabs here. The player nav is deliberately untouched —
           * its own pass belongs to the quality-of-life workstream, and
           * rebuilding it twice would be the only thing worse than leaving it.
           */}
          {!showingAdmin && (
            <>
              {me?.capabilities.play && (
                <NavLink to="/challenges" className="text-sm hover:underline">
                  Challenges
                </NavLink>
              )}
              {me?.capabilities.view_scoreboard && (
                <NavLink to="/scoreboard" className="text-sm hover:underline">
                  Scoreboard
                </NavLink>
              )}
              <NavLink to="/character" className="text-sm hover:underline">
                Character
              </NavLink>
              <NavLink to="/party" className="text-sm hover:underline">
                Party
              </NavLink>
            </>
          )}

          <span className="ml-auto flex items-center gap-3">
            {me?.capabilities.play && <NotificationCentre />}
            <ThemePicker />
            {isAdmin && !showingAdmin && (
              // The way in. The way back out is at the foot of the admin
              // sidebar (spec 049 §7), where it is beside the rest of the admin
              // chrome rather than floating above it. Player view is the
              // default so an admin sees the event as a player does.
              <button
                onClick={enterAdminView}
                className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-raised"
              >
                Admin view
              </button>
            )}
            {me && (
              <>
                <Avatar
                  userId={me.user.id}
                  displayName={me.user.display_name}
                  hasAvatar={me.user.has_avatar}
                  size={28}
                />
                <button
                  onClick={() => signOut.mutate()}
                  className="text-sm hover:underline"
                >
                  Sign out
                </button>
              </>
            )}
          </span>
        </div>
      </nav>
      <Outlet />
      <AssistantPanel />
    </div>
  );
}
