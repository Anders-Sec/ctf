import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSkillsPage from "./AdminSkillsPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = [{ id: "s1", name: "Hacking", display_order: 0, description: null }];
const CATEGORIES = [
  { id: "c1", name: "Web", slug: "web", display_order: 0, skill_id: null },
  { id: "c2", name: "Crypto", slug: "crypto", display_order: 1, skill_id: "s1" },
];

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.endsWith("/admin/skills")) {
      if (init?.method === "POST") {
        return { status: 201, body: { id: "s2", ...JSON.parse(String(init.body)), description: null } };
      }
      return { status: 200, body: SKILLS };
    }
    if (path.endsWith("/admin/categories")) {
      return { status: 200, body: CATEGORIES };
    }
    if (path.includes("/admin/categories/") && path.endsWith("/skill")) {
      return { status: 200, body: { ...CATEGORIES[0], skill_id: "s1" } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminSkillsPage />);
  return mock;
}

describe("AdminSkillsPage", () => {
  it("lists skills and categories with their mapping", async () => {
    render();
    // The Crypto category is pre-mapped to Hacking; finding its selector also
    // waits for both queries to resolve.
    const select = (await screen.findByLabelText("Skill for Crypto")) as HTMLSelectElement;
    expect(select.value).toBe("s1");
    // Hacking appears both as a skill row and as a selectable option.
    expect(screen.getAllByText("Hacking").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("creates a skill", async () => {
    const fetchMock = render();
    const input = await screen.findByLabelText("New skill name");

    await userEvent.type(input, "Forensics");
    await userEvent.click(screen.getByRole("button", { name: "Add skill" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/skills") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ name: "Forensics" });
    });
  });

  it("maps a category to a skill", async () => {
    const fetchMock = render();
    const select = await screen.findByLabelText("Skill for Web");

    await userEvent.selectOptions(select, "s1");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/categories/c1/skill") &&
          init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ skill_id: "s1" });
    });
  });
});
