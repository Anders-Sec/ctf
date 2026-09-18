import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ActivityTicker, { ago } from "./ActivityTicker";
import type { ActivityItem } from "../api/scoreboard";

beforeEach(() => {
  localStorage.clear();
});

function solve(overrides: Partial<ActivityItem> = {}): ActivityItem {
  return {
    kind: "solve",
    display_name: "Rin",
    zone_name: "Networking",
    challenge_title: null,
    tier: null,
    tier_level: null,
    at: new Date().toISOString(),
    ...overrides,
  };
}

describe("ago", () => {
  it("is coarse, and says just now rather than 0m ago", () => {
    const now = Date.now();
    expect(ago(new Date(now - 5_000).toISOString())).toBe("just now");
    expect(ago(new Date(now - 5 * 60_000).toISOString())).toBe("5m ago");
    expect(ago(new Date(now - 3 * 3600_000).toISOString())).toBe("3h ago");
    expect(ago(new Date(now - 2 * 86400_000).toISOString())).toBe("2d ago");
  });

  it("never goes negative on a clock a little ahead", () => {
    expect(ago(new Date(Date.now() + 10_000).toISOString())).toBe("just now");
  });
});

describe("ActivityTicker", () => {
  it("names the zone for a solve, and no challenge", () => {
    render(<ActivityTicker items={[solve()]} />);

    // §3: naming the challenge would hand every watcher a solvable-work list.
    expect(screen.getByText(/cleared something in/)).toBeInTheDocument();
    expect(screen.getByText("Networking")).toBeInTheDocument();
  });

  it("names a boss in full, with its tier colour", () => {
    render(
      <ActivityTicker
        items={[
          solve({
            kind: "boss",
            display_name: "Vek",
            challenge_title: "The Gatekeeper",
            tier: "city",
            tier_level: 3,
          }),
        ]}
      />,
    );

    // Spec 032 already broadcasts these by name; being first is the point.
    const name = screen.getByText("The Gatekeeper");
    expect(name).toBeInTheDocument();
    expect(name.className).toContain("text-boss-city");
  });

  it("says the dungeon is quiet rather than collapsing", () => {
    render(<ActivityTicker items={[]} />);

    expect(screen.getByText(/The dungeon is quiet/)).toBeInTheDocument();
  });

  it("shows at most ten", () => {
    const many = Array.from({ length: 20 }, (_, index) =>
      solve({ display_name: `Player ${index}` }),
    );

    render(<ActivityTicker items={many} />);

    const list = screen.getByRole("list", { name: "Recent activity" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
  });

  it("collapses, and remembers it", async () => {
    const { unmount } = render(<ActivityTicker items={[solve()]} />);

    await userEvent.click(screen.getByRole("button", { name: /In the dungeon/ }));
    expect(screen.queryByRole("list", { name: "Recent activity" })).not.toBeInTheDocument();

    // "I find this distracting" is what collapsing is for, and it needs no
    // server-side preference (spec 069 §7.2).
    unmount();
    render(<ActivityTicker items={[solve()]} />);
    expect(screen.queryByRole("list", { name: "Recent activity" })).not.toBeInTheDocument();
  });

  it("renders with storage it cannot read", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    render(<ActivityTicker items={[solve()]} />);

    expect(screen.getByRole("list", { name: "Recent activity" })).toBeInTheDocument();
    getItem.mockRestore();
  });
});
