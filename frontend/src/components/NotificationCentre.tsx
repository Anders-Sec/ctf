import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  dismissMany,
  dismissOne,
  markAllRead,
  type AppNotification,
  type NotificationKind,
} from "../api/notifications";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useNotifications } from "../hooks/useNotifications";
import { KINDS_IN, metaFor, type InboxTab } from "./notificationKinds";

/**
 * The inbox (specs 028, 065).
 *
 * Two tabs rather than one stream, split by **audience**: "Yours" is what
 * happened to you, "Event" is what happened. A player checking "did I level" and
 * a player checking "what did I miss" are doing different jobs, and one list
 * makes both worse.
 *
 * Toasts are the other half. They are deliberately quiet now — four seconds,
 * top-left under this button, and **impossible to click** — because the
 * complaint was never their content, it was having to dismiss them. Not
 * everything toasts either: see `KIND_META`.
 */
const MAX_TOASTS = 3;

export default function NotificationCentre() {
  const { unread, items, toasts, dismiss, live } = useNotifications();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<InboxTab>("yours");
  const [kind, setKind] = useState<string>("");
  const queryClient = useQueryClient();
  const panel = useRef<HTMLDivElement>(null);

  // The inbox had no Escape and no focus handling at all: it opened, and the
  // keyboard stayed on the button behind it.
  useDialogFocus(panel, { onClose: () => setOpen(false), active: open });

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["notifications"] });

  const readAll = useMutation({ mutationFn: markAllRead, onSuccess: refresh });
  const clearOne = useMutation({ mutationFn: dismissOne, onSuccess: refresh });
  const clearMany = useMutation({
    mutationFn: (kinds: NotificationKind[]) => dismissMany(kinds),
    onSuccess: refresh,
  });

  const inTab = (item: AppNotification, which: InboxTab) => metaFor(item.kind).tab === which;
  const counts = {
    yours: items.filter((item) => inTab(item, "yours") && !item.read).length,
    event: items.filter((item) => inTab(item, "event") && !item.read).length,
  };

  const shown = items
    .filter((item) => inTab(item, tab))
    .filter((item) => (kind ? item.kind === kind : true));

  const clearVisible = () => {
    // Scoped to the tab, so clearing the news cannot take your own record with
    // it. "Yours" asks first: it is a player's history of their own event.
    const kinds = kind ? [kind as NotificationKind] : KINDS_IN[tab];
    if (tab === "yours" && !window.confirm("Clear your own record of these?")) return;
    clearMany.mutate(kinds);
  };

  return (
    <>
      <button
        data-tour="inbox"
        onClick={() => setOpen((was) => !was)}
        aria-label={unread ? `Inbox, ${unread} unread` : "Inbox"}
        // A plain icon with its count beside it (spec 064 §2). The box made an
        // incidental control look like a primary one.
        className="flex shrink-0 items-center gap-1 rounded p-1 text-base leading-none text-content-muted hover:bg-surface-sunken hover:text-content"
      >
        <span aria-hidden>✉</span>
        {unread > 0 && (
          <span className="rounded-full bg-accent px-1.5 text-xs font-semibold text-accent-content tabular-nums">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-label="Inbox"
          // Anchored left since spec 064: on the right it opened over the
          // assistant panel and the rest of the busy corner.
          className="absolute left-4 top-14 z-40 flex max-h-[70vh] w-96 max-w-[calc(100vw-2rem)] flex-col rounded border border-border-strong bg-surface shadow-xl"
        >
          <div className="flex shrink-0 items-center gap-1 border-b border-border p-2">
            {(["yours", "event"] as const).map((value) => (
              <button
                key={value}
                onClick={() => {
                  setTab(value);
                  setKind("");
                }}
                aria-pressed={tab === value}
                className={`rounded px-2 py-1 text-sm ${
                  tab === value ? "bg-content text-surface" : "hover:bg-surface-raised"
                }`}
              >
                {value === "yours" ? "Yours" : "Event"}
                {counts[value] > 0 && (
                  <span className="ml-1 text-xs tabular-nums">{counts[value]}</span>
                )}
              </button>
            ))}
            <button
              onClick={() => setOpen(false)}
              aria-label="Close inbox"
              className="ml-auto px-1 text-lg leading-none"
            >
              ×
            </button>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-2 py-1.5 text-xs">
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              aria-label="Filter by kind"
              className="rounded border border-border-strong bg-surface-raised px-1 py-0.5"
            >
              <option value="">All kinds</option>
              {KINDS_IN[tab].map((value) => (
                <option key={value} value={value}>
                  {metaFor(value).label}
                </option>
              ))}
            </select>
            {unread > 0 && (
              <button onClick={() => readAll.mutate()} className="hover:underline">
                Mark all read
              </button>
            )}
            {shown.length > 0 && (
              <button
                onClick={clearVisible}
                disabled={clearMany.isPending}
                className="ml-auto hover:underline disabled:opacity-50"
              >
                Clear {kind ? "these" : tab === "yours" ? "Yours" : "Event"}
              </button>
            )}
          </div>

          {!live && (
            // Worth saying: the feed is still correct, it just is not live.
            <p className="shrink-0 px-3 py-1 text-xs text-content-muted">
              Not connected — new messages will appear when you reload.
            </p>
          )}

          <ul className="min-h-0 flex-1 overflow-y-auto p-2">
            {shown.length === 0 ? (
              <li className="px-1 py-3 text-sm text-content-muted">
                {tab === "yours"
                  ? "Nothing yet. Go and do something."
                  : "No news yet."}
              </li>
            ) : (
              shown.map((item) => (
                <li key={item.id} className="mb-2 last:mb-0">
                  <Row
                    item={item}
                    onNavigate={() => setOpen(false)}
                    onClear={() => clearOne.mutate(item.id)}
                  />
                </li>
              ))
            )}
          </ul>
        </div>
      )}

      {/* Top-left, under the inbox, so a toast never lands on the assistant
          panel — and capped, so a burst of solves is not a column. */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed left-4 top-16 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.slice(0, MAX_TOASTS).map((toast) => (
          <Toast key={toast.id} item={toast} onDone={() => dismiss(toast.id)} />
        ))}
      </div>
    </>
  );
}

function Row({
  item,
  onNavigate,
  onClear,
}: {
  item: AppNotification;
  onNavigate: () => void;
  onClear: () => void;
}) {
  const meta = metaFor(item.kind);

  const inner = (
    <>
      <p className="text-sm font-semibold">{item.title}</p>
      <p className="mt-0.5 text-sm text-content-muted">{item.body}</p>
    </>
  );

  return (
    <div
      className={`rounded border px-3 py-2 ${
        item.read ? "border-border bg-surface-raised" : "border-accent/50 bg-accent/10"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        {/* Colour *and* the kind named: nine near-identical glyphs is exactly
            the case spec 048's rule exists for. */}
        <span className={`text-xs ${meta.tone}`}>
          <span aria-hidden className="mr-1">
            {meta.icon}
          </span>
          {meta.label}
        </span>
        <button
          onClick={onClear}
          aria-label={`Clear ${item.title}`}
          className="shrink-0 text-xs text-content-muted hover:underline"
        >
          Clear
        </button>
      </div>
      {item.link ? (
        <Link to={item.link} onClick={onNavigate} className="mt-1 block hover:underline">
          {inner}
        </Link>
      ) : (
        <div className="mt-1">{inner}</div>
      )}
    </div>
  );
}

/**
 * Four seconds, and nothing to click.
 *
 * The complaint was *"I'm always clicking out of them"* — so there is no button
 * and `pointer-events-none` means it cannot intercept a click aimed at whatever
 * is underneath. The inbox is the record either way.
 */
function Toast({ item, onDone }: { item: AppNotification; onDone: () => void }) {
  const meta = metaFor(item.kind);

  useEffect(() => {
    const timer = setTimeout(onDone, 4000);
    return () => clearTimeout(timer);
  }, [onDone]);

  return (
    <div
      role="status"
      className="pointer-events-none rounded border border-border-strong bg-surface-overlay p-3 shadow-lg"
    >
      <p className={`text-xs ${meta.tone}`}>
        <span aria-hidden className="mr-1">
          {meta.icon}
        </span>
        {meta.label}
      </p>
      <p className="mt-0.5 text-sm font-semibold">{item.title}</p>
      <p className="mt-0.5 text-sm text-content-muted">{item.body}</p>
    </div>
  );
}
