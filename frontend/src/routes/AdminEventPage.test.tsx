import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminEventPage from "./AdminEventPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({
          capabilities: capabilities({ view_admin: true, administer: true }),
        }),
      };
    }
    if (path.endsWith("/admin/event-config")) {
      if (init?.method === "PATCH") {
        return { status: 200, body: JSON.parse(String(init.body)) };
      }
      return {
        status: 200,
        body: {
          name: "Autumn Crawl",
          starts_at: "2026-09-01T09:00:00Z",
          ends_at: "2026-09-03T17:00:00Z",
          registration_open: true,
          assistant_enabled: true,
          server_time: "2026-09-02T12:00:00Z",
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminEventPage />);
  return mock;
}

describe("AdminEventPage", () => {
  it("loads the current config into the form", async () => {
    render();
    expect(await screen.findByDisplayValue("Autumn Crawl")).toBeInTheDocument();
  });

  it("saves an edited name", async () => {
    const fetchMock = render();
    const nameInput = await screen.findByDisplayValue("Autumn Crawl");

    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Winter Crawl");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/event-config") &&
          init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        name: "Winter Crawl",
      });
    });
  });
});
