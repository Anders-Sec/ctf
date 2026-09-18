import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getNotifications,
  type AppNotification,
} from "../api/notifications";
import { metaFor } from "../components/notificationKinds";

function notificationSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/ws/notifications`;
}

/**
 * The System AI talking to this player (spec 028).
 *
 * The backlog fetched over REST is the record; the socket is what makes a
 * message arrive while the player is looking at the screen. If the socket never
 * connects the feature still works — it just stops being live.
 *
 * New arrivals are queued as toasts — but **only the kinds that earn an
 * interruption** (spec 065 §5). A boss kill is interesting once and irrelevant
 * the forty-first time, and at 200 players it is the loudest thing on the
 * platform and the least about you; it lands in the inbox and bumps the badge
 * instead. An admin saying "the network is back" still interrupts.
 *
 * Only a few show at once: one solve can award an achievement, a level and the
 * zone it opened, and three overlapping popups is the point at which they stop
 * being readable.
 */
const MAX_TOASTS = 3;

export function useNotifications() {
  const queryClient = useQueryClient();
  const feed = useQuery({ queryKey: ["notifications"], queryFn: getNotifications });
  const [toasts, setToasts] = useState<AppNotification[]>([]);
  const [live, setLive] = useState(false);
  //: Ids already shown, so a refetch of the backlog cannot re-pop something the
  //: player has already seen this session.
  const seen = useRef<Set<string>>(new Set());

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let socket: WebSocket | null = null;

    const connect = () => {
      if (closed) return;
      socket = new WebSocket(notificationSocketUrl());

      socket.onopen = () => {
        attempt = 0;
        setLive(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as AppNotification;
          if (seen.current.has(message.id)) return;
          seen.current.add(message.id);
          // Marked seen either way: a kind that does not toast must still not
          // start toasting if the socket redelivers it.
          if (metaFor(message.kind).toasts) {
            setToasts((current) => [...current, message].slice(-MAX_TOASTS));
          }
          // The socket carries the message; the count and backlog still come
          // from the one place that is authoritative.
          queryClient.invalidateQueries({ queryKey: ["notifications"] });
        } catch {
          // A malformed frame is not worth tearing the connection down for.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setLive(false);
        // Backs off, so a backend restart does not turn 200 browsers into a
        // stampede — the same rule the scoreboard socket follows.
        const delay = Math.min(1000 * 2 ** attempt, 30_000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient]);

  return {
    unread: feed.data?.unread ?? 0,
    items: feed.data?.items ?? [],
    isPending: feed.isPending,
    toasts,
    dismiss,
    live,
  };
}
