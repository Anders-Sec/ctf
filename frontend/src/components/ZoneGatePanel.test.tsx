import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ZoneGatePanel from "./ZoneGatePanel";
import type { GraphZone } from "../api/dungeon";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const INTRO: GraphZone = {
  id: "z1",
  name: "Intro",
  slug: "intro",
  reachable: true,
  published_challenges: 3,
  gates: [],
};

const NETWORKING: GraphZone = {
  id: "z2",
  name: "Networking",
  slug: "networking",
  reachable: true,
  published_challenges: 4,
  gates: [
    {
      id: "g1",
      requirement_type: "percent_in_category",
      description: "Clear 100% of Intro",
      required_category_id: "z1",
      required_category_name: "Intro",
      required_skill_id: null,
      required_skill_name: null,
      threshold: 100,
      source_has_no_challenges: false,
    },
  ],
};

function render(zone: GraphZone, { eventRunning = false } = {}) {
  return renderApp(
    <ZoneGatePanel
      zone={zone}
      zones={[INTRO, NETWORKING]}
      skills={[]}
      eventRunning={eventRunning}
      onClose={vi.fn()}
    />,
  );
}

describe("ZoneGatePanel", () => {
  it("lists what opens the zone", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    render(NETWORKING);

    expect(screen.getByText("Clear 100% of Intro")).toBeInTheDocument();
  });

  it("says plainly when a zone opens from the start", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    render(INTRO);

    expect(screen.getByText(/open from the start/i)).toBeInTheDocument();
  });

  it("adds a connection by adding a gate that names a source zone", async () => {
    const fetchMock = stubFetch(() => ({ status: 201, body: {} }));
    render(INTRO);

    await userEvent.selectOptions(screen.getByLabelText("Source zone"), "z2");
    await userEvent.clear(screen.getByLabelText("Percent to clear"));
    await userEvent.type(screen.getByLabelText("Percent to clear"), "50");
    await userEvent.click(screen.getByRole("button", { name: "Add gate" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/categories/z1/requirements"),
      );
      expect(call).toBeDefined();
      // A connection *is* a requirement — there is no separate edge to create.
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        requirement_type: "percent_in_category",
        required_category_id: "z2",
        threshold: 50,
      });
    });
  });

  it("only offers the fields the chosen gate type uses", async () => {
    stubFetch(() => ({ status: 200, body: {} }));
    render(INTRO);

    expect(screen.getByLabelText("Source zone")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Condition"), "min_xp");

    // An XP gate has no source zone, and sending one would be refused.
    expect(screen.queryByLabelText("Source zone")).not.toBeInTheDocument();
    expect(screen.getByLabelText("XP")).toBeInTheDocument();
  });

  it("names the loop when a gate would close one", async () => {
    stubFetch(() => ({
      status: 409,
      body: {
        error: {
          code: "requirement_cycle",
          message: "That gate would close a loop: Intro → Networking → Intro.",
        },
      },
    }));
    render(INTRO);

    await userEvent.selectOptions(screen.getByLabelText("Source zone"), "z2");
    await userEvent.click(screen.getByRole("button", { name: "Add gate" }));

    // The server's own prose beats ours here: it names the loop, and a generic
    // "invalid requirement" would leave an admin hunting through 22 zones.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Intro → Networking → Intro/,
    );
  });

  it("removes a gate", async () => {
    const fetchMock = stubFetch(() => ({ status: 200, body: { message: "ok" } }));
    render(NETWORKING);

    await userEvent.click(
      screen.getByRole("button", { name: "Remove gate: Clear 100% of Intro" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/requirements/g1"),
      );
      expect(call?.[1]?.method).toBe("DELETE");
    });
  });

  it("warns when a gate points at a zone with nothing in it", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    render({
      ...NETWORKING,
      gates: [{ ...NETWORKING.gates[0], source_has_no_challenges: true }],
    });

    // The bug that sealed the whole dungeon in 019: 100% of an empty zone is
    // never reached.
    expect(screen.getByText(/has nothing published/i)).toBeInTheDocument();
  });

  it("says when changing gates mid-event will re-lock zones", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    render(NETWORKING, { eventRunning: true });

    expect(screen.getByText(/re-locks zones/i)).toBeInTheDocument();
  });
});
