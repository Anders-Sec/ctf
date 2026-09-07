import { useMutation } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { logout } from "../api/auth";
import { useAdminView } from "../auth/adminView";
import { useSession } from "../auth/session";
import AssistantPanel from "./AssistantPanel";
import Avatar from "./Avatar";

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
  const enterPlayerView = () => {
    setAdminView(false);
    navigate("/");
  };

  return (
    <div className="min-h-screen">
      <nav className="border-b border-stone bg-white/40">
        <div className="mx-auto flex max-w-3xl items-center gap-4 p-4">
          <NavLink to="/" className="font-semibold">
            CTF
          </NavLink>

          {showingAdmin ? (
            <>
              <NavLink to="/admin" end className="text-sm hover:underline">
                Console
              </NavLink>
              <NavLink to="/admin/ops" className="text-sm hover:underline">
                Ops
              </NavLink>
              <NavLink to="/admin/signals" className="text-sm hover:underline">
                Signals
              </NavLink>
              <NavLink to="/admin/assistant" className="text-sm hover:underline">
                AI flags
              </NavLink>
              <NavLink to="/admin/instances" className="text-sm hover:underline">
                Dungeons
              </NavLink>
              <NavLink to="/admin/challenges" className="text-sm hover:underline">
                Manage
              </NavLink>
              <NavLink to="/admin/users" className="text-sm hover:underline">
                Approvals
              </NavLink>
            </>
          ) : (
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
              <NavLink to="/party" className="text-sm hover:underline">
                Party
              </NavLink>
            </>
          )}

          <span className="ml-auto flex items-center gap-3">
            {isAdmin && (
              // The one cross-over control. Player view is the default so an
              // admin can see the event as a player does.
              <button
                onClick={showingAdmin ? enterPlayerView : enterAdminView}
                className="rounded border border-stone px-2 py-1 text-xs hover:bg-white/60"
              >
                {showingAdmin ? "Player view" : "Admin view"}
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
                <button onClick={() => signOut.mutate()} className="text-sm hover:underline">
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
