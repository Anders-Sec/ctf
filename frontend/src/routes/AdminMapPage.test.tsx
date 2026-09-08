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

function render({ administer = true }: { administer?: boolean } = {}) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer }) }),
      };
    }
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

  it("does not offer editing to someone who cannot administer", async () => {
    render({ administer: false });

    expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reset layout" }),
    ).not.toBeInTheDocument();
  });
});
