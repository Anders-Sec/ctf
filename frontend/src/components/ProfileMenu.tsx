import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { logout } from "../api/auth";
import { getMyStanding } from "../api/scoreboard";
import { useSession } from "../auth/session";
import { useDialogFocus } from "../hooks/useDialogFocus";
import Avatar from "./Avatar";
import { openTour } from "./Tour";

/**
 * The profile, and everything that used to clutter the bar (spec 064 §2.1).
 *
 * Sign out was a permanent fixture for a once-an-event action, sitting beside
 * Settings, which is nearly as rare. Both live here now, with Admin view, and
 * the bar gets its corner back.
 *
 * The chip carries **your own** level and XP. That is the rule as 064 §7.1
 * states it: never another player's, and never on a board — your own, in your
 * own chrome, is yours to see.
 */
export default function ProfileMenu({
  isAdmin,
  onEnterAdminView,
}: {
  isAdmin: boolean;
  onEnterAdminView: () => void;
}) {
  const { me } = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  // Only fetched once the menu is opened: the bar renders on every page and has
  // no business pulling a scoreboard projection to do it.
  const standing = useQuery({
    queryKey: ["scoreboard", "me"],
    queryFn: getMyStanding,
    enabled: open,
  });

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      // Clear everything: another player may sign in on this browser next.
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });

  // **A menu is not a dialog** (spec 071 §4): focus moves in and Escape gives it
  // back, but Tab is *not* trapped. Tab walks out of a menu everywhere else on
  // the web, and a menu that swallowed it would be the odd one out.
  const menu = useRef<HTMLDivElement>(null);
  useDialogFocus(menu, { onClose: () => setOpen(false), trap: false, active: open });

  // An outside click closes it too, because a menu that only closes on its own
  // button is one people leave open.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  if (!me) return null;

  const span = me.xp_into_level + me.xp_to_next;
  const percent = span > 0 ? Math.min(100, Math.round((me.xp_into_level / span) * 100)) : 100;

  return (
    <div ref={wrapper} className="relative">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${me.user.display_name}, level ${me.level}`}
        className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-sunken"
      >
        <span className="hidden text-right sm:block">
          <span className="block text-xs font-medium leading-tight tabular-nums">
            Lv {me.level}
          </span>
          <span
            aria-hidden
            className="mt-0.5 block h-1 w-12 overflow-hidden rounded-full bg-surface-sunken"
          >
            <span className="block h-full bg-accent-strong" style={{ width: `${percent}%` }} />
          </span>
        </span>
        <Avatar
          userId={me.user.id}
          displayName={me.user.display_name}
          hasAvatar={me.user.has_avatar}
          size={28}
        />
        <span aria-hidden className="text-xs text-content-muted">
          ▾
        </span>
      </button>

      {open && (
        <div
          ref={menu}
          tabIndex={-1}
          role="menu"
          aria-label="Profile"
          className="absolute right-0 top-full z-40 mt-1 w-64 rounded border border-border-strong bg-surface-overlay p-3 shadow-xl"
        >
          <p className="truncate font-medium">{me.user.display_name}</p>

          <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
            <Stat label="Level" value={String(me.level)} />
            <Stat
              label="Rank"
              value={
                standing.data?.rank == null ? "—" : `#${standing.data.rank}`
              }
            />
            <Stat
              label="Party"
              value={
                standing.data?.team_rank == null ? "—" : `#${standing.data.team_rank}`
              }
            />
          </dl>

          <p className="mt-2 text-xs text-content-muted tabular-nums">
            {me.xp_to_next > 0
              ? `${me.xp_into_level.toLocaleString()} / ${span.toLocaleString()} XP to level ${me.level + 1}`
              : "Top of the curve for now"}
          </p>

          <div className="mt-3 flex flex-col border-t border-border pt-2 text-sm">
            <MenuLink to="/character" onChoose={() => setOpen(false)}>
              Character sheet
            </MenuLink>
            <MenuLink to="/settings" onChoose={() => setOpen(false)}>
              Settings
            </MenuLink>
            {/* Dismissing the tour is not a one-way door (spec 066 §3.2). */}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                openTour();
              }}
              className="rounded px-2 py-1 text-left hover:bg-surface-raised"
            >
              Show the tour again
            </button>
            {isAdmin && (
              // The way in. The way back out is at the foot of the admin
              // sidebar (spec 049 §7), unchanged.
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  onEnterAdminView();
                }}
                className="rounded px-2 py-1 text-left hover:bg-surface-raised"
              >
                Admin view
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              onClick={() => signOut.mutate()}
              disabled={signOut.isPending}
              className="rounded px-2 py-1 text-left hover:bg-surface-raised disabled:opacity-50"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-surface-raised py-1">
      <dd className="font-semibold tabular-nums">{value}</dd>
      <dt className="text-content-muted">{label}</dt>
    </div>
  );
}

function MenuLink({
  to,
  onChoose,
  children,
}: {
  to: string;
  onChoose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      role="menuitem"
      onClick={onChoose}
      className="rounded px-2 py-1 hover:bg-surface-raised"
    >
      {children}
    </Link>
  );
}
