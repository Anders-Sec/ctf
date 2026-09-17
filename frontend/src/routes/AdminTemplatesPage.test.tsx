import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminTemplatesPage from "./AdminTemplatesPage";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

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

function render(templates: unknown[] = []) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.endsWith("/admin/templates")) {
      return { status: 200, body: templates };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminTemplatesPage />);
  return mock;
}

describe("AdminTemplatesPage", () => {
  it("is a page of its own, not a section under the live instances", async () => {
    // Spec 049 §4: runtime state and setup configuration shared one route, on
    // two different clocks. This page is setup.
    render([template()]);

    expect(
      await screen.findByRole("heading", { level: 1, name: /container templates/i }),
    ).toBeInTheDocument();
  });

  it("sends the default lifetime when the field is cleared, never zero", async () => {
    // A cleared number input reads as "" and Number("") is 0. Saved as a
    // lifetime, that expired a team's container about a minute after launch.
    const fetchMock = render();
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
    const fetchMock = render([template()]);
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
