import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminChallengesPage from "./AdminChallengesPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }) };
    }
    if (path.endsWith("/categories")) {
      return { status: 200, body: [{ id: "cat1", name: "Forensics", slug: "forensics" }] };
    }
    if (path.endsWith("/admin/challenges") && init?.method === "POST") {
      return {
        status: 201,
        body: {
          id: "ch1",
          title: "New",
          slug: "new",
          category: { id: "cat9", name: "Web Exploitation", slug: "web-exploitation" },
        },
      };
    }
    if (path.endsWith("/admin/challenges")) {
      return { status: 200, body: [] };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminChallengesPage />, { route: "/admin/challenges" });
  return mock;
}

describe("AdminChallengesPage category field", () => {
  it("offers existing categories as suggestions and submits a typed name", async () => {
    const fetchMock = render();

    await userEvent.click(await screen.findByRole("button", { name: /new challenge/i }));

    // The existing category is offered as a datalist suggestion.
    await waitFor(() => {
      const options = document.querySelectorAll("#category-options option");
      expect(Array.from(options).some((o) => o.getAttribute("value") === "Forensics")).toBe(true);
    });

    await userEvent.type(screen.getByLabelText(/title/i), "Packet Puzzle");
    // A brand-new category name, typed freely.
    await userEvent.type(screen.getByLabelText(/category/i), "Web Exploitation");
    await userEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/challenges") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        category: "Web Exploitation",
      });
    });
  });
});

const CHALLENGE = {
  id: "ch1",
  title: "Packet Puzzle",
  slug: "packet-puzzle",
  category: { id: "cat1", name: "Forensics", slug: "forensics", description: null, display_order: 0 },
  difficulty: "hard",
  state: "draft",
  release_at: null,
  pre_release_state: "hidden",
  initial_points: 200,
  minimum_points: 80,
  decay_threshold: 40,
  scoring: "static",
  decay_basis: "players",
  max_attempts: null,
  container_template_id: null,
  current_value: 200,
  solve_count: 0,
  answers: [],
  artifacts: [],
  prerequisites: [],
  body: "",
};

function renderWithChallenge() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.includes("/admin/challenges/ch1") && init?.method === "DELETE") {
      return { status: 200, body: { message: "Deleted." } };
    }
    // Sub-resources first: a bare includes() would swallow them and hand back
    // the challenge object where an array is expected.
    if (path.includes("/admin/challenges/ch1/")) {
      return { status: 200, body: [] };
    }
    if (path.includes("/admin/challenges/ch1")) {
      return { status: 200, body: CHALLENGE };
    }
    if (path.endsWith("/admin/challenges")) {
      return { status: 200, body: [CHALLENGE] };
    }
    if (path.endsWith("/categories")) return { status: 200, body: [] };
    if (path.endsWith("/admin/skills")) return { status: 200, body: [] };
    return { status: 200, body: [] };
  });
  renderApp(<AdminChallengesPage />, { route: "/admin/challenges" });
  return mock;
}

describe("deleting a challenge", () => {
  it("asks first, naming the challenge", async () => {
    renderWithChallenge();

    await userEvent.click(await screen.findByRole("button", { name: /Packet Puzzle/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete challenge" }));

    // A generic "are you sure" gets clicked through; naming it does not.
    expect(screen.getByText("Packet Puzzle", { selector: "strong" })).toBeInTheDocument();
  });

  it("does not delete unless the confirmation is taken", async () => {
    const fetchMock = renderWithChallenge();

    await userEvent.click(await screen.findByRole("button", { name: /Packet Puzzle/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete challenge" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE"),
    ).toBe(false);
  });

  it("deletes once confirmed", async () => {
    const fetchMock = renderWithChallenge();

    await userEvent.click(await screen.findByRole("button", { name: /Packet Puzzle/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete challenge" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete it" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/challenges/ch1") && init?.method === "DELETE",
      );
      expect(call).toBeTruthy();
    });
  });
});
