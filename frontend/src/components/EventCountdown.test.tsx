import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EventCountdown, { format } from "./EventCountdown";
import type { EventSummary } from "../api/auth";

afterEach(() => {
  vi.useRealTimers();
});

function event(overrides: Partial<EventSummary> = {}): EventSummary {
  return {
    name: "Vault of the Forgotten Flag",
    starts_at: "2026-09-14T09:00:00Z",
    ends_at: "2026-09-19T17:00:00Z",
    registration_open: true,
    server_time: "2026-09-17T13:00:00Z",
    ...overrides,
  };
}

describe("format", () => {
  it("is coarse at a distance and precise near the end", () => {
    // "2d 4h" is what somebody wants on day one; seconds only matter later.
    expect(format(2 * 86400_000 + 4 * 3600_000)).toBe("2d 4h");
    expect(format(4 * 3600_000 + 30 * 60_000)).toBe("4h 30m");
    expect(format(90_000)).toBe("1m 30s");
  });

  it("never counts below zero", () => {
    expect(format(-5000)).toBe("0m 0s");
  });
});

describe("EventCountdown", () => {
  it("counts from the server's clock, not the browser's", () => {
    // The whole point: 200 browsers with 200 slightly wrong clocks must not
    // disagree about how long is left (spec 066 §2.1).
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T14:00:00Z")); // an hour fast

    render(<EventCountdown event={event()} />);

    // Server says 13:00 on the 17th; the end is 17:00 on the 19th. That is
    // 2d 4h, which is what a correct clock would also show.
    expect(screen.getByText("2d 4h")).toBeInTheDocument();
  });

  it("counts to the start before the doors open", () => {
    vi.useFakeTimers();
    render(
      <EventCountdown
        event={event({ server_time: "2026-09-14T07:00:00Z" })}
      />,
    );

    expect(screen.getByText(/until the doors open/)).toBeInTheDocument();
    expect(screen.getByText("2h 0m")).toBeInTheDocument();
  });

  it("stops rather than counting negatives once it is over", () => {
    vi.useFakeTimers();
    render(<EventCountdown event={event({ server_time: "2026-09-20T09:00:00Z" })} />);

    expect(screen.getByText("The crawl is over.")).toBeInTheDocument();
  });

  it("renders nothing without an event, or without an end", () => {
    const { container: none } = render(<EventCountdown event={null} />);
    expect(none).toBeEmptyDOMElement();

    vi.useFakeTimers();
    const { container: endless } = render(
      <EventCountdown event={event({ starts_at: null, ends_at: null })} />,
    );
    expect(endless).toBeEmptyDOMElement();
  });
});
