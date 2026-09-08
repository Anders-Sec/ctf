import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSkillsPage from "./AdminSkillsPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = [
  {
    id: "s1",
    name: "Injection Artistry",
    display_order: 0,
    description: null,
    kind: "useful",
    category_id: "c1",
  },
  {
    id: "s2",
    name: "Magic Smoke Attraction",
    display_order: 1,
    description: null,
    kind: "funny",
    category_id: "c1",
  },
];
const CATEGORIES = [
  { id: "c1", name: "Web", slug: "web", display_order: 0, ability: "str" },
  { id: "c2", name: "Crypto", slug: "crypto", display_order: 1, ability: "int" },
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
    if (path.includes("/admin/categories/") && path.endsWith("/ability")) {
      return { status: 200, body: { ...CATEGORIES[0], ability: "dex" } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminSkillsPage />);
  return mock;
}

describe("AdminSkillsPage", () => {
  it("lists skills and the ability each category feeds", async () => {
    render();
    const select = (await screen.findByLabelText("Ability for Crypto")) as HTMLSelectElement;
    expect(select.value).toBe("int");
    expect(screen.getByText("Injection Artistry")).toBeInTheDocument();
    // Funny skills are marked, so an admin can tell the jokes apart.
    expect(screen.getByText("funny")).toBeInTheDocument();
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

  it("points a category at an ability", async () => {
    const fetchMock = render();
    const select = await screen.findByLabelText("Ability for Web");

    await userEvent.selectOptions(select, "dex");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/categories/c1/ability") &&
          init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ ability: "dex" });
    });
  });
});
