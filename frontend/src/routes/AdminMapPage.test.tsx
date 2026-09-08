import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminMapPage from "./AdminMapPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const MAP = {
  fog_of_war: true,
  zones: [
    {
      id: "z1",
      name: "Intro",
      slug: "intro",
      ability: "int",
      display_order: 0,
      x: 40,
      y: 40,
      locked: false,
      unlock_requirements: [],
      cleared: 0,
      total: 2,
    },
  ],
  edges: [],
};

const GRAPH = {
  zones: [
    {
      id: "z1",
      name: "Intro",
      slug: "intro",
      reachable: true,
      published_challenges: 2,
      gates: [],
    },
    {
      id: "z2",
      name: "Networking",
      slug: "networking",
      reachable: false,
      published_challenges: 0,
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
    },
  ],
};

function render({ administer = true }: { administer?: boolean } = {}) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer }) }),
      };
    }
    // Before /map: "/admin/map/graph" also ends with "/graph", not "/map".
    if (path.endsWith("/admin/map/graph")) return { status: 200, body: GRAPH };
    if (path.endsWith("/admin/skills")) return { status: 200, body: [] };
    if (path.endsWith("/map")) return { status: 200, body: MAP };
    return { status: 200, body: { message: "ok" } };
  });
  renderApp(<AdminMapPage />);
  return mock;
}

describe("AdminMapPage", () => {
  it("shows the map and offers a way back to the derived layout", async () => {
    const fetchMock = render();

    expect(await screen.findByLabelText("Dungeon map")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reset layout" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/map/reset-layout"),
      );
      expect(call?.[1]?.method).toBe("POST");
    });
  });

  it("warns about zones nobody can reach", async () => {
    render();

    // The flag exists because a stranded zone has no symptom on the map itself:
    // it just quietly never opens.
    expect(await screen.findByText(/1 zone is unreachable/i)).toBeInTheDocument();
  });

  it("does not offer editing to someone who cannot administer", async () => {
    render({ administer: false });

    expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reset layout" }),
    ).not.toBeInTheDocument();
  });
});
