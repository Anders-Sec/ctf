import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminClassesPage from "./AdminClassesPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = [{ id: "s1", name: "Hacking", display_order: 0, description: null }];
const CLASSES = [
  {
    id: "cl1",
    name: "Rogue",
    display_order: 0,
    description: null,
    affinity_skill_id: null,
  },
];

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.endsWith("/admin/classes")) {
      if (init?.method === "POST") {
        return {
          status: 201,
          body: {
            id: "cl2",
            display_order: 0,
            description: null,
            affinity_skill_id: null,
            ...JSON.parse(String(init.body)),
          },
        };
      }
      return { status: 200, body: CLASSES };
    }
    if (path.includes("/admin/classes/") && init?.method === "PATCH") {
      return { status: 200, body: { ...CLASSES[0], affinity_skill_id: "s1" } };
    }
    if (path.endsWith("/admin/skills")) return { status: 200, body: SKILLS };
    return { status: 200, body: {} };
  });
  renderApp(<AdminClassesPage />);
  return mock;
}

describe("AdminClassesPage", () => {
  it("lists classes with their affinity skill", async () => {
    render();
    const select = (await screen.findByLabelText(
      "Affinity skill for Rogue",
    )) as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByRole("option", { name: "Hacking" })).toBeInTheDocument();
  });

  it("creates a class", async () => {
    const fetchMock = render();
    const input = await screen.findByLabelText("New class name");

    await userEvent.type(input, "Wizard");
    await userEvent.click(screen.getByRole("button", { name: "Add class" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/classes") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ name: "Wizard" });
    });
  });

  it("sets a class's affinity skill", async () => {
    const fetchMock = render();
    const select = await screen.findByLabelText("Affinity skill for Rogue");

    await userEvent.selectOptions(select, "s1");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/classes/cl1") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        affinity_skill_id: "s1",
      });
    });
  });
});
