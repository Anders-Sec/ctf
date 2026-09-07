import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import InstancePanel from "./InstancePanel";
import type { Instance } from "../api/instances";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function instance(overrides: Partial<Instance> = {}): Instance {
  return {
    id: "i1",
    challenge_id: "c1",
    status: "running",
    connection_url: "https://dm-abc.ctf-nm.org",
    expires_at: "2026-09-07T18:00:00Z",
    error: null,
    ...overrides,
  };
}

interface Options {
  getStatus?: number;
  getBody?: unknown;
  launchBody?: unknown;
  launchStatus?: number;
}

function render(options: Options = {}) {
  const {
    getStatus = 404,
    getBody = { error: { code: "not_found", message: "none" } },
    launchBody = instance({ status: "pending", connection_url: null }),
    launchStatus = 201,
  } = options;

  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.endsWith("/challenges/c1/instance") && init?.method === "POST") {
      return { status: launchStatus, body: launchBody };
    }
    if (path.endsWith("/challenges/c1/instance") && init?.method === "DELETE") {
      return { status: 204, body: undefined };
    }
    if (path.endsWith("/challenges/c1/instance")) {
      return { status: getStatus, body: getBody };
    }
    return { status: 200, body: {} };
  });
  renderApp(<InstancePanel challengeId="c1" />);
  return mock;
}

describe("InstancePanel", () => {
  it("offers to summon a dungeon when there is none", async () => {
    render();
    expect(
      await screen.findByRole("button", { name: /summon your dungeon/i }),
    ).toBeInTheDocument();
  });

  it("sends a launch when summoned", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByRole("button", { name: /summon your dungeon/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            String(path).endsWith("/challenges/c1/instance") && init?.method === "POST",
        ),
      ).toBe(true);
    });
  });

  it("shows the link once running", async () => {
    render({ getStatus: 200, getBody: instance() });

    const link = await screen.findByRole("link", { name: /enter the dungeon/i });
    expect(link).toHaveAttribute("href", "https://dm-abc.ctf-nm.org");
  });

  it("explains a reached cap rather than a raw error", async () => {
    render({
      launchStatus: 409,
      launchBody: { error: { code: "instance_cap_reached", message: "too many" } },
    });
    await userEvent.click(await screen.findByRole("button", { name: /summon your dungeon/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/as many live targets/i);
  });

  it("surfaces a failed dungeon instead of spinning", async () => {
    render({ getStatus: 200, getBody: instance({ status: "failed", error: "ImagePullBackOff" }) });

    expect(await screen.findByText(/collapsed as it formed/i)).toBeInTheDocument();
  });
});
