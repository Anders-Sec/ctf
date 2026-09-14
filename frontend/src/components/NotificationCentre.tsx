import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { markAllRead, type AppNotification } from "../api/notifications";
import { useNotifications } from "../hooks/useNotifications";

/**
 * The System AI's voice on screen (spec 028).
 *
 * Toasts, not a modal: interrupting someone mid-challenge to say "you levelled
 * up" is a punishment rather than a reward. Everything also lands in the
 * backlog behind the bell, which is the record — a player who was offline, or
 * who let a toast fade, finds it there.
 */
const ICON: Record<string, string> = {
  achievement: "★",
  class_unlocked: "◈",
  zone_unlocked: "⌸",
  level_up: "▲",
  ability_milestone: "◆",
  boss_kill: "☠",
  announcement: "❖",
  dispatch: "▤",
  system: "▸",
};

export default function NotificationCentre() {
  const { unread, items, toasts, dismiss, live } = useNotifications();
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();

  const readAll = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <>
      <button
        onClick={() => setOpen((was) => !was)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative rounded border border-stone px-2 py-1 text-sm hover:bg-white/60"
      >
        <span aria-hidden>✉</span>
        {unread > 0 && (
          <span className="ml-1 rounded-full bg-torch px-1.5 text-xs font-semibold text-parchment tabular-nums">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-4 top-14 z-40 max-h-[70vh] w-96 overflow-y-auto rounded border border-stone bg-parchment p-3 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
              From the System AI
            </h2>
            <div className="flex items-center gap-2">
              {unread > 0 && (
                <button
                  onClick={() => readAll.mutate()}
                  className="text-xs hover:underline"
                >
                  Mark all read
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                aria-label="Close notifications"
                className="text-xs hover:underline"
              >
                Close
              </button>
            </div>
          </div>

          {!live && (
            // Worth saying: the feed is still correct, it just is not live.
            <p className="mt-2 text-xs text-muted">
              Not connected — new messages will appear when you reload.
            </p>
          )}

          {items.length === 0 ? (
            <p className="mt-3 text-sm text-muted">Nothing yet. Go and do something.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {items.map((item) => (
                <li
                  key={item.id}
                  className={`rounded border px-3 py-2 ${
                    item.read ? "border-stone bg-white/30" : "border-torch/50 bg-torch/10"
                  }`}
                >
                  <Body item={item} onNavigate={() => setOpen(false)} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Toasts sit outside the panel so they show whether or not it is open. */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
      >
        {toasts.map((toast) => (
          <Toast key={toast.id} item={toast} onDone={() => dismiss(toast.id)} />
        ))}
      </div>
    </>
  );
}

function Body({ item, onNavigate }: { item: AppNotification; onNavigate: () => void }) {
  const inner = (
    <>
      <p className="text-sm font-semibold">
        <span aria-hidden className="mr-1 text-torch">
          {ICON[item.kind] ?? ICON.system}
        </span>
        {item.title}
      </p>
      <p className="mt-0.5 text-sm text-muted">{item.body}</p>
    </>
  );
  return item.link ? (
    <Link to={item.link} onClick={onNavigate} className="block hover:underline">
      {inner}
    </Link>
  ) : (
    <div>{inner}</div>
  );
}

function Toast({ item, onDone }: { item: AppNotification; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 7000);
    return () => clearTimeout(timer);
  }, [onDone]);

  return (
    <div
      role="status"
      className="pointer-events-auto rounded border border-torch/60 bg-ink/95 p-3 text-parchment shadow-lg"
    >
      <p className="text-sm font-semibold">
        <span aria-hidden className="mr-1 text-torch">
          {ICON[item.kind] ?? ICON.system}
        </span>
        {item.title}
      </p>
      <p className="mt-0.5 text-sm opacity-90">{item.body}</p>
      <button
        onClick={onDone}
        className="mt-2 text-xs underline opacity-70 hover:opacity-100"
      >
        Dismiss
      </button>
    </div>
  );
}
