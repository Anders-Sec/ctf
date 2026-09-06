import { useEffect, useRef, useState } from "react";

import { scoreboardSocketUrl, type Boards } from "../api/scoreboard";

type Status = "connecting" | "live" | "offline";

/**
 * Both boards, pushed.
 *
 * Every message is a whole board rather than a diff, so a dropped connection
 * costs nothing but a reconnect — there is no state to reconcile. Reconnection
 * backs off so a backend restart does not turn 200 browsers into a stampede.
 */
export function useLiveScoreboard(): { boards: Boards | null; status: Status } {
  const [boards, setBoards] = useState<Boards | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      const socket = new WebSocket(scoreboardSocketUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        attempt = 0;
        setStatus("live");
      };
      socket.onmessage = (event) => {
        try {
          setBoards(JSON.parse(event.data) as Boards);
        } catch {
          // A malformed frame is not worth tearing the connection down for.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setStatus("offline");
        // Exponential backoff, capped: a restart must not produce a stampede
        // of 200 browsers all reconnecting in the same instant.
        const delay = Math.min(1000 * 2 ** attempt, 30_000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socketRef.current?.close();
    };
  }, []);

  return { boards, status };
}
