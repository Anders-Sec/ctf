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
    template_name: "vault",
    status: "running",
    owner_label: "party: The Bold",
    connection_url: "https://dm-abc.ctf-nm.org",
    created_at: "2026-09-07T10:00:00Z",
    expires_at: "2026-09-07T11:00:00Z",
    error: null,
    ...overrides,
  };
}

function template(overrides: Record<string, unknown> = {}) {
  return {
    id: "t1",
    name: "web-registry",
    image: "ghcr.io/anders-sec/ctf-web-registry",
    image_tag: "sha-abc",
    container_port: 8080,
    protocol: "http",
    ttl_seconds: 90,
    injects_answer: true,
    shared_instance: true,
    cpu_limit: "500m",
    memory_limit: "384Mi",
    readiness_path: "/",
    ...overrides,
  };
}

function render(instances: AdminInstance[], templates: unknown[] = []) {
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
    if (path.endsWith("/admin/templates")) {
      return { status: 200, body: templates };
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

  it("sends the default lifetime when the field is cleared, never zero", async () => {
    // A cleared number input reads as "" and Number("") is 0. Saved as a
    // lifetime, that expired a team's container about a minute after launch.
    const fetchMock = render([]);
    await screen.findByRole("button", { name: /new template/i });
    await userEvent.click(screen.getByRole("button", { name: /new template/i }));

    await userEvent.type(screen.getByLabelText(/^name$/i), "web-registry");
    await userEvent.type(screen.getByLabelText(/^image$/i), "ghcr.io/x/y");
    await userEvent.clear(screen.getByLabelText(/lifetime/i));
    await userEvent.click(screen.getByRole("button", { name: /create template/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/templates") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call![1]!.body)).ttl_seconds).toBe(3600);
    });
  });

  it("corrects a template's lifetime in place, without deleting it", async () => {
    // A short lifetime expired a team's container almost as soon as they
    // launched it, and deleting the template would have unbound every
    // challenge that used it.
    const fetchMock = render([], [template()]);
    await screen.findByText("web-registry");

    await userEvent.click(screen.getByRole("button", { name: /lifetime/i }));
    const field = screen.getByLabelText(/lifetime for web-registry/i);
    await userEvent.clear(field);
    await userEvent.type(field, "7200");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/templates/t1") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call![1]!.body)).ttl_seconds).toBe(7200);
    });
  });
});
