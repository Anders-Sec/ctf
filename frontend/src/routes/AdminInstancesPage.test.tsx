import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminInstancesPage from "./AdminInstancesPage";
import type { AdminInstance } from "../api/adminInstances";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function inst(overrides: Partial<AdminInstance> = {}): AdminInstance {
  return {
    id: "i1",
    challenge_id: "c1",
    challenge_title: "Sealed Vault",
    status: "running",
    owner_label: "party: The Bold",
    connection_url: "https://dm-abc.ctf-nm.org",
    created_at: "2026-09-07T10:00:00Z",
    expires_at: "2026-09-07T11:00:00Z",
    error: null,
    ...overrides,
  };
}

function render(instances: AdminInstance[]) {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.includes("/admin/instances/") && init?.method === "DELETE") {
      return { status: 204, body: undefined };
    }
    if (path.endsWith("/admin/instances")) {
      return { status: 200, body: instances };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminInstancesPage />);
  return mock;
}

describe("AdminInstancesPage", () => {
  it("lists running dungeons with their owners", async () => {
    render([inst()]);

    expect(await screen.findByText("Sealed Vault")).toBeInTheDocument();
    expect(screen.getByText(/party: The Bold/)).toBeInTheDocument();
  });

  it("tears one down", async () => {
    const fetchMock = render([inst()]);
    await screen.findByText("Sealed Vault");

    await userEvent.click(screen.getByRole("button", { name: /tear down/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            String(path).includes("/admin/instances/i1") && init?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });

  it("says so when nothing is running", async () => {
    render([]);
    expect(await screen.findByText(/nothing running/i)).toBeInTheDocument();
  });
});
