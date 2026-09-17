import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSkillsPage from "./AdminSkillsPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  // Groups remember their collapsed state per admin, so a shut group in one
  // test would hide another test's rows.
  window.localStorage.clear();
});

const SKILLS = [
  {
    id: "s1",
    name: "Injection Artistry",
    display_order: 0,
    description: "Making a database confess.",
    kind: "useful",
    category_id: "c1",
    challenge_count: 12,
  },
  {
    id: "s2",
    name: "Magic Smoke Attraction",
    display_order: 1,
    description: null,
    kind: "funny",
    category_id: "c1",
    challenge_count: 0,
  },
  {
    id: "s3",
    name: "Frequency Analysis",
    display_order: 2,
    description: "Counting letters until they talk.",
    kind: "useful",
    category_id: null,
    challenge_count: 3,
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
    if (path.endsWith("/admin/skills/bulk")) {
      return { status: 200, body: { changed: 2, refused: {} } };
    }
    if (path.endsWith("/admin/skills")) {
      if (init?.method === "POST") {
        return {
          status: 201,
          body: { id: "s9", challenge_count: 0, ...JSON.parse(String(init.body)) },
        };
      }
      return { status: 200, body: SKILLS };
    }
    if (path.includes("/admin/skills/") && init?.method === "PATCH") {
      return { status: 200, body: { ...SKILLS[0], ...JSON.parse(String(init.body)) } };
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
  it("groups skills by zone, with a summary per group and (no zone) last", async () => {
    render();

    const headings = await screen.findAllByRole("button", { expanded: true });
    const groups = headings.map((heading) => heading.textContent ?? "");
    // Crypto holds nothing here, so it is not rendered at all — an empty group
    // is noise, not information.
    expect(groups.some((text) => text.includes("Web"))).toBe(true);
    expect(groups.some((text) => text.includes("(no zone)"))).toBe(true);
    expect(groups.findIndex((text) => text.includes("Web"))).toBeLessThan(
      groups.findIndex((text) => text.includes("(no zone)")),
    );

    // The summary is what makes collapsing safe: a shut group still says what
    // is inside it.
    expect(screen.getByText(/2 skills · 1 funny · 12 challenges/)).toBeInTheDocument();
  });

  it("marks a skill no challenge feeds, in the list rather than only the drawer", async () => {
    render();
    await screen.findByText("Magic Smoke Attraction");

    // XP that lands nowhere on anybody's sheet.
    const row = screen.getByText("Magic Smoke Attraction").closest("li");
    expect(within(row as HTMLElement).getByText("unattached")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("funny")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("no copy")).toBeInTheDocument();
  });

  it("filters by kind", async () => {
    render();
    await screen.findByText("Injection Artistry");

    await userEvent.selectOptions(await screen.findByLabelText("Kind"), "funny");

    expect(screen.getByText("Magic Smoke Attraction")).toBeInTheDocument();
    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
  });

  it("filters to the skills attached to nothing from the problem count", async () => {
    render();
    await screen.findByText("Injection Artistry");

    await userEvent.click(screen.getByRole("button", { name: /attached to nothing/ }));

    expect(screen.getByText("Magic Smoke Attraction")).toBeInTheDocument();
    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
    expect(screen.getByText("1 of 3 shown")).toBeInTheDocument();
  });

  it("searches by name", async () => {
    render();
    await screen.findByText("Injection Artistry");

    await userEvent.type(screen.getByLabelText("Search skills"), "smoke");

    expect(screen.getByText("Magic Smoke Attraction")).toBeInTheDocument();
    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
  });

  it("sets kind and zone from the drawer, which no UI could do before", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Injection Artistry"));

    const drawer = screen.getByRole("dialog");
    await userEvent.selectOptions(within(drawer).getByLabelText("Skill kind"), "funny");
    await userEvent.selectOptions(within(drawer).getByLabelText("Skill zone"), "c2");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/skills/s1") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        kind: "funny",
        category_id: "c2",
      });
    });
  });

  it("warns before closing a drawer with unsaved changes", async () => {
    render();
    await userEvent.click(await screen.findByText("Injection Artistry"));

    const drawer = screen.getByRole("dialog");
    await userEvent.type(within(drawer).getByLabelText("Skill name"), "!");
    await userEvent.click(within(drawer).getByRole("button", { name: "Close editor" }));

    // Still open, asking — losing an edit silently is worse than a click.
    expect(screen.getByText("Close without saving?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("creates a skill with every field, not just a name", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByRole("button", { name: "+ New skill" }));

    const drawer = screen.getByRole("dialog");
    await userEvent.type(within(drawer).getByLabelText("Skill name"), "Forensics");
    await userEvent.selectOptions(within(drawer).getByLabelText("Skill kind"), "funny");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) => String(path).endsWith("/admin/skills") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        name: "Forensics",
        kind: "funny",
      });
    });
  });

  it("runs a bulk kind change over the selection and reports the result", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByLabelText("Select Injection Artistry"));
    await userEvent.click(screen.getByLabelText("Select Magic Smoke Attraction"));

    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Set kind for selected"), "useful");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/skills/bulk"),
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        ids: ["s1", "s2"],
        action: "set_kind",
        value: "useful",
      });
    });
    expect(await screen.findByText(/2 changed/)).toBeInTheDocument();
  });

  it("points a category at an ability", async () => {
    const fetchMock = render();
    const select = await screen.findByLabelText("Ability for Web");

    await userEvent.selectOptions(select, "dex");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/categories/c1/ability") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ ability: "dex" });
    });
  });

  it("hides the write controls from a read-only viewer", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) {
        return {
          status: 200,
          body: me({ capabilities: capabilities({ view_admin: true, administer: false }) }),
        };
      }
      if (path.endsWith("/admin/skills")) return { status: 200, body: SKILLS };
      if (path.endsWith("/admin/categories")) return { status: 200, body: CATEGORIES };
      return { status: 200, body: {} };
    });
    renderApp(<AdminSkillsPage />);

    await screen.findByText("Injection Artistry");
    expect(screen.queryByRole("button", { name: "+ New skill" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Select Injection Artistry")).not.toBeInTheDocument();
  });
});
