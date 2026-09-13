import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAchievementsPage from "./AdminAchievementsPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PLACEHOLDER = "TODO: System AI flavour text.";

const ROSTER = [
  {
    id: "a1",
    code: "first_blood",
    name: "First Blood",
    description: "Noted, for whatever that is worth.",
    earned_by: "Solving your first challenge.",
    display_order: 0,
    secret: false,
    has_trigger: true,
    needs_copy: false,
    held_by: 12,
  },
  {
    id: "a2",
    code: "nice_try",
    name: "Nice Try",
    description: PLACEHOLDER,
    earned_by: "Triggering the challenge-integrity guardrail.",
    display_order: 1,
    secret: false,
    has_trigger: false,
    needs_copy: true,
    held_by: 0,
  },
];

function render({ administer = true } = {}) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer }) }),
      };
    }
    if (path.endsWith("/admin/achievements/triggers")) {
      return { status: 200, body: { registered: ["first_blood"], unused: ["blitz"] } };
    }
    if (path.endsWith("/admin/achievements")) return { status: 200, body: ROSTER };
    return { status: 200, body: { message: "ok" } };
  });
  renderApp(<AdminAchievementsPage />);
  return mock;
}

describe("AdminAchievementsPage", () => {
  it("lists the roster with its criteria", async () => {
    render();

    expect(await screen.findByText("First Blood")).toBeInTheDocument();
    expect(screen.getByText("Solving your first challenge.")).toBeInTheDocument();
  });

  it("marks a row whose code has no trigger", async () => {
    render();

    // Inert rows never fire. Finding that out here beats finding out after the
    // event when nobody earned it.
    expect(await screen.findByText("no trigger")).toBeInTheDocument();
  });

  it("flags rows still holding the placeholder description", async () => {
    render();

    expect(await screen.findByText("needs copy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /needs copy \(1\)/i })).toBeInTheDocument();
  });

  it("filters down to the rows still needing copy", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: /needs copy \(1\)/i }));

    expect(screen.getByText("Nice Try")).toBeInTheDocument();
    expect(screen.queryByText("First Blood")).not.toBeInTheDocument();
  });

  it("offers unused trigger codes as suggestions", async () => {
    render();

    await screen.findByText("First Blood");
    expect(screen.getByText(/no achievement yet: blitz/i)).toBeInTheDocument();
  });

  it("creates one", async () => {
    const fetchMock = render();

    await userEvent.type(await screen.findByLabelText("New achievement code"), "blitz");
    await userEvent.type(screen.getByLabelText("New achievement name"), "Blitz");
    await userEvent.click(screen.getByRole("button", { name: "Add achievement" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/achievements") && init?.method === "POST",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        code: "blitz",
        name: "Blitz",
      });
    });
  });

  it("saves hand-written copy without touching the code", async () => {
    const fetchMock = render();

    await userEvent.click((await screen.findAllByRole("button", { name: "Edit" }))[1]!);
    const body = screen.getByLabelText("Description for nice_try");
    await userEvent.clear(body);
    await userEvent.type(body, "Noted.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path, init]) =>
        String(path).includes("/admin/achievements/a2") && init?.method === "PATCH",
      );
      const sent = JSON.parse(String(call?.[1]?.body));
      expect(sent.description).toBe("Noted.");
      // The code joins to a trigger and to every award already granted.
      expect(sent).not.toHaveProperty("code");
    });
  });

  it("will not let a held achievement be deleted", async () => {
    render();

    await screen.findByText("First Blood");
    const [heldDelete] = screen.getAllByRole("button", { name: "Delete" });

    // Taking an earned achievement back off a player is worse than a bad name.
    expect(heldDelete).toBeDisabled();
  });

  it("allows deleting one nobody holds", async () => {
    const fetchMock = render();

    await screen.findByText("Nice Try");
    const deletes = screen.getAllByRole("button", { name: "Delete" });
    await userEvent.click(deletes[1]!);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path, init]) =>
        String(path).includes("/admin/achievements/a2") && init?.method === "DELETE",
      );
      expect(call).toBeDefined();
    });
  });

  it("is read-only for staff who cannot administer", async () => {
    render({ administer: false });

    expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add achievement" }),
    ).not.toBeInTheDocument();
  });
});
