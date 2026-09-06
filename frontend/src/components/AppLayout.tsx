import { useMutation } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { logout } from "../api/auth";
import { useSession } from "../auth/session";
import Avatar from "./Avatar";

export default function AppLayout() {
  const { me } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      // Clear everything: another player may sign in on this browser next.
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });

  return (
    <div className="min-h-screen">
      <nav className="border-b border-stone bg-white/40">
        <div className="mx-auto flex max-w-3xl items-center gap-4 p-4">
          <NavLink to="/" className="font-semibold">
            CTF
          </NavLink>
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
          {me?.capabilities.view_admin && (
            <>
              <NavLink to="/admin/challenges" className="text-sm hover:underline">
                Manage
              </NavLink>
              <NavLink to="/admin/users" className="text-sm hover:underline">
                Approvals
              </NavLink>
            </>
          )}

          {me && (
            <span className="ml-auto flex items-center gap-3">
              <Avatar
                userId={me.user.id}
                displayName={me.user.display_name}
                hasAvatar={me.user.has_avatar}
                size={28}
              />
              <button onClick={() => signOut.mutate()} className="text-sm hover:underline">
                Sign out
              </button>
            </span>
          )}
        </div>
      </nav>
      <Outlet />
    </div>
  );
}
