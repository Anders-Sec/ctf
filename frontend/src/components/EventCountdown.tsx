import { useEffect, useState } from "react";

import type { EventSummary } from "../api/auth";

/**
 * How long is left (spec 066 §2.1).
 *
 * **Offset against the server's clock, never the browser's.** `EventSummary`
 * carries `server_time` with the note that it is *"the clock that actually
 * decides; the client's own is decorative"* — and the home page's own docstring
 * makes the same point about the gates: 200 browsers with 200 slightly wrong
 * clocks would otherwise disagree about how long is left.
 *
 * So the offset is measured once on mount and every tick is drawn from it. A
 * machine an hour fast shows the same figure as one that is right.
 *
 * Deliberately *not* `AdminLayout`'s `EventClock`, which spec §2.1 expected to
 * reuse: that one prints the server's wall-clock time from a different payload
 * shape. Recorded in §8.
 */
export default function EventCountdown({ event }: { event: EventSummary | null }) {
  const [now, setNow] = useState(() => serverNow(event));

  useEffect(() => {
    if (!event) return;
    const offset = Date.parse(event.server_time) - Date.now();
    const tick = () => setNow(Date.now() + offset);
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [event]);

  if (!event) return null;

  const starts = event.starts_at ? Date.parse(event.starts_at) : null;
  const ends = event.ends_at ? Date.parse(event.ends_at) : null;

  // Before the doors open it counts to the start; after the end it says so and
  // stops, rather than counting negatives at somebody.
  if (starts !== null && now < starts) {
    return <Line label="until the doors open" ms={starts - now} />;
  }
  if (ends !== null && now >= ends) {
    return <p className="text-sm text-content-muted">The crawl is over.</p>;
  }
  if (ends === null) return null;

  return <Line label="left" ms={ends - now} />;
}

function serverNow(event: EventSummary | null): number {
  return event ? Date.parse(event.server_time) : Date.now();
}

function Line({ label, ms }: { label: string; ms: number }) {
  return (
    <p className="text-sm text-content-muted">
      <span className="font-medium text-content tabular-nums">{format(ms)}</span> {label}
    </p>
  );
}

/**
 * Coarse on purpose. "2 days, 4 hours" is what somebody wants on day one;
 * seconds only start mattering near the end, so they only appear then.
 */
export function format(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${seconds % 60}s`;
}
