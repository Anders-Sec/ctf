import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import ChallengeTable from "./ChallengeTable";
import type {
  AdminChallengeSummary,
  ZoneSummary,
} from "../api/adminChallenges";

function zone(overrides: Partial<ZoneSummary> = {}): ZoneSummary {
  return {
    category_id: "z1",
    name: "Networking",
    slug: "networking",
    display_order: 0,
    challenge_count: 2,
    total_xp: 1900,
    boss_challenge_id: null,
    boss_tier: null,
    draft_count: 0,
    published_count: 2,
    ...overrides,
  };
}

function challenge(
  overrides: Partial<AdminChallengeSummary> = {},
): AdminChallengeSummary {
  return {
    id: "c1",
    title: "Port of Call",
    slug: "port-of-call",
    category: {
      id: "z1",
      name: "Networking",
      slug: "networking",
      description: null,
      display_order: 0,
    },
    difficulty: "easy",
    state: "draft",
    effective_state: "draft",
    release_at: null,
    solve_count: 0,
    current_value: 100,
    initial_points: 100,
    boss_tier: null,
    ai_ladder_level: null,
    has_container: false,
    answer_count: 1,
    hint_count: 0,
    skill_count: 2,
    prerequisite_count: 0,
    ...overrides,
  } as AdminChallengeSummary;
}

/** The table drives selection through its parent, so the harness holds it. */
function Harness({
  challenges,
  zones,
  onSelected,
}: {
  challenges: AdminChallengeSummary[];
  zones: ZoneSummary[];
  onSelected?: (ids: string[]) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <QueryClientProvider client={new QueryClient()}>
      <ChallengeTable
        challenges={challenges}
        zones={zones}
        canWrite
        selected={selected}
        onSelectedChange={(next) => {
          setSelected(next);
          onSelected?.([...next]);
        }}
        openId={null}
        onOpen={() => undefined}
        collapsed={new Set()}
        onToggleZone={() => undefined}
      />
    </QueryClientProvider>
  );
}

describe("ChallengeTable", () => {
  it("groups rows under their zone in dungeon order, not alphabetically", () => {
    render(
      <Harness
        zones={[
          zone({ category_id: "z2", name: "Aardvark", slug: "aardvark", display_order: 9 }),
          zone({ category_id: "z1", name: "Zebra", slug: "zebra", display_order: 1 }),
        ]}
        challenges={[
          challenge({ id: "a", title: "In Aardvark", category: { id: "z2", name: "Aardvark", slug: "aardvark", description: null, display_order: 9 } }),
          challenge({ id: "b", title: "In Zebra" }),
        ]}
      />,
    );

    const headings = screen.getAllByRole("button", { expanded: true });
    // The zones prop is already ordered by the API; the table must not re-sort.
    expect(headings[0]).toHaveTextContent("Aardvark");
    expect(headings[1]).toHaveTextContent("Zebra");
  });

  it("flags a zone that has drifted off its XP budget", () => {
    render(
      <Harness
        zones={[zone({ total_xp: 1050 })]}
        challenges={[challenge()]}
      />,
    );

    // Spec 040 lets each challenge carry its own XP, so a zone can drift
    // silently. The header is where that shows up.
    expect(screen.getByText("1,050/1,900 XP")).toBeInTheDocument();
  });

  it("says when a zone has no boss", () => {
    render(<Harness zones={[zone()]} challenges={[challenge()]} />);

    expect(screen.getByText("no boss")).toBeInTheDocument();
  });

  it("shows a zero count for a challenge with no flag", () => {
    render(
      <Harness
        zones={[zone()]}
        challenges={[challenge({ answer_count: 0 })]}
      />,
    );

    expect(screen.getByTitle("0 flags")).toBeInTheDocument();
  });

  it("selects a range on shift-click", async () => {
    const seen: string[][] = [];
    render(
      <Harness
        zones={[zone()]}
        challenges={[
          challenge({ id: "c1", title: "One" }),
          challenge({ id: "c2", title: "Two" }),
          challenge({ id: "c3", title: "Three" }),
        ]}
        onSelected={(ids) => seen.push(ids)}
      />,
    );

    // One session for all of it: the bare `userEvent.click` helpers each start
    // a fresh one, which drops a held modifier before the click lands.
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Select One"));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByLabelText("Select Three"));
    await user.keyboard("{/Shift}");

    // Inclusive of both ends, and everything between.
    expect(seen.at(-1)).toEqual(["c1", "c2", "c3"]);
  });

  it("selects a whole zone from its header", async () => {
    const seen: string[][] = [];
    render(
      <Harness
        zones={[zone()]}
        challenges={[
          challenge({ id: "c1", title: "One" }),
          challenge({ id: "c2", title: "Two" }),
        ]}
        onSelected={(ids) => seen.push(ids)}
      />,
    );

    await userEvent.click(screen.getByLabelText("Select all in Networking"));

    expect(seen.at(-1)).toEqual(["c1", "c2"]);
  });

  it("edits XP in place without opening anything", async () => {
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        bodies.push(String(init?.body ?? ""));
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    render(<Harness zones={[zone()]} challenges={[challenge()]} />);

    const field = screen.getByLabelText("XP for Port of Call");
    await userEvent.clear(field);
    await userEvent.type(field, "175");
    await userEvent.tab();

    // Saved on blur, straight from the row — no drawer, no save button.
    await waitFor(() =>
      expect(bodies.some((b) => b.includes("initial_points") && b.includes("175"))).toBe(
        true,
      ),
    );
    vi.unstubAllGlobals();
  });

  it("renders nothing but a note when the filter matches nothing", () => {
    render(<Harness zones={[zone()]} challenges={[]} />);

    expect(screen.getByText("Nothing matches.")).toBeInTheDocument();
  });

  it("drops a zone the filter emptied rather than showing an empty header", () => {
    render(
      <Harness
        zones={[zone(), zone({ category_id: "z9", name: "Empty", slug: "empty" })]}
        challenges={[challenge()]}
      />,
    );

    expect(screen.queryByText("Empty")).not.toBeInTheDocument();
    const header = screen.getByRole("button", { expanded: true });
    expect(within(header).getByText("Networking")).toBeInTheDocument();
  });
});
