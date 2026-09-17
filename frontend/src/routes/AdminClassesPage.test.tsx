import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminClassesPage from "./AdminClassesPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  window.localStorage.clear();
});

const SKILLS = [
  {
    id: "s1",
    name: "Hacking",
    display_order: 0,
    description: null,
    kind: "useful",
    category_id: null,
    challenge_count: 4,
  },
  {
    id: "s2",
    name: "Lockpicking",
    display_order: 1,
    description: null,
    kind: "useful",
    category_id: null,
    challenge_count: 2,
  },
];

const CLASSES = [
  {
    id: "cl1",
    name: "Rogue",
    display_order: 0,
    description: "Quiet, and gone before the alarm.",
    rarity: "common",
    preferences: [{ ability: "dex", skill_id: null }],
    requirements: [{ skill_id: "s1", min_level: 3 }],
    preference_count: 1,
    requirement_count: 1,
    wearers: 6,
  },
  {
    id: "cl2",
    name: "Archmage",
    display_order: 1,
    description: null,
    rarity: "mythic",
    preferences: [],
    requirements: [],
    preference_count: 0,
    requirement_count: 0,
    wearers: 0,
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
    if (path.endsWith("/admin/classes/bulk")) {
      return {
        status: 200,
        body: { changed: 1, refused: { cl1: "6 players are wearing it" } },
      };
    }
    if (path.endsWith("/admin/classes")) {
      if (init?.method === "POST") {
        return {
          status: 201,
          body: {
            id: "cl9",
            preferences: [],
            requirements: [],
            preference_count: 0,
            requirement_count: 0,
            wearers: 0,
            ...JSON.parse(String(init.body)),
          },
        };
      }
      return { status: 200, body: CLASSES };
    }
    if (path.includes("/admin/classes/") && path.endsWith("/preferences")) {
      return { status: 200, body: CLASSES[0] };
    }
    if (path.includes("/admin/classes/") && path.endsWith("/requirements")) {
      return { status: 200, body: CLASSES[0] };
    }
    if (path.includes("/admin/classes/") && init?.method === "PATCH") {
      return { status: 200, body: { ...CLASSES[0], ...JSON.parse(String(init.body)) } };
    }
    if (path.endsWith("/admin/skills")) return { status: 200, body: SKILLS };
    return { status: 200, body: {} };
  });
  renderApp(<AdminClassesPage />);
  return mock;
}

describe("AdminClassesPage", () => {
  it("groups classes by rarity, with the rarity named as well as coloured", async () => {
    render();

    await screen.findByText("Rogue");
    const headings = screen.getAllByRole("button", { expanded: true });
    const groups = headings.map((heading) => heading.textContent ?? "");
    expect(groups.some((text) => text.includes("common"))).toBe(true);
    expect(groups.some((text) => text.includes("mythic"))).toBe(true);
    // Rarity is never colour alone.
    const row = screen.getByText("Archmage").closest("li");
    expect(within(row as HTMLElement).getByText("mythic")).toBeInTheDocument();
  });

  it("shows the counts a row is scanned by, and marks an ungated class", async () => {
    render();
    await screen.findByText("Rogue");

    const rogue = screen.getByText("Rogue").closest("li") as HTMLElement;
    expect(within(rogue).getByText("1 pref · 1 req")).toBeInTheDocument();
    expect(within(rogue).getByText("6 players")).toBeInTheDocument();

    const archmage = screen.getByText("Archmage").closest("li") as HTMLElement;
    expect(within(archmage).getByText("ungated")).toBeInTheDocument();
  });

  it("filters to the classes with no requirements", async () => {
    render();
    await screen.findByText("Rogue");

    await userEvent.selectOptions(screen.getByLabelText("Requirements"), "no");

    expect(screen.getByText("Archmage")).toBeInTheDocument();
    expect(screen.queryByText("Rogue")).not.toBeInTheDocument();
  });

  it("searches by name", async () => {
    render();
    await screen.findByText("Rogue");

    await userEvent.type(screen.getByLabelText("Search classes"), "arch");

    expect(screen.getByText("Archmage")).toBeInTheDocument();
    expect(screen.queryByText("Rogue")).not.toBeInTheDocument();
  });

  it("sets rarity from the drawer, which no UI could do before", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Rogue"));

    const drawer = screen.getByRole("dialog");
    await userEvent.selectOptions(within(drawer).getByLabelText("Class rarity"), "rare");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/classes/cl1") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ rarity: "rare" });
    });
  });

  it("edits preferences and requirements — the whole of the recommender", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Rogue"));
    const drawer = screen.getByRole("dialog");

    // A preference is an ability or a skill, never both — the XOR the model
    // enforces, expressed as a kind switch rather than two fields.
    await userEvent.selectOptions(
      within(drawer).getByLabelText("Preference 1 kind"),
      "skill",
    );
    await userEvent.click(within(drawer).getByRole("button", { name: "+ Add requirement" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const prefs = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/classes/cl1/preferences"),
      );
      expect(prefs).toBeTruthy();
      expect(JSON.parse(String(prefs?.[1]?.body))).toEqual({
        preferences: [{ ability: null, skill_id: "s1" }],
      });

      const reqs = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/admin/classes/cl1/requirements"),
      );
      expect(reqs).toBeTruthy();
      expect(JSON.parse(String(reqs?.[1]?.body))).toEqual({
        requirements: [
          { skill_id: "s1", min_level: 3 },
          { skill_id: "s1", min_level: 1 },
        ],
      });
    });
  });

  it("refuses to delete a class players are wearing", async () => {
    render();
    await userEvent.click(await screen.findByText("Rogue"));

    const drawer = screen.getByRole("dialog");
    // The FK is SET NULL, so deleting would silently return them to Classless.
    expect(within(drawer).getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("creates a class", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByRole("button", { name: "+ New class" }));

    const drawer = screen.getByRole("dialog");
    await userEvent.type(within(drawer).getByLabelText("Class name"), "Wizard");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) => String(path).endsWith("/admin/classes") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ name: "Wizard" });
    });
  });

  it("reports a partial bulk failure rather than hiding it behind a success", async () => {
    render();
    await userEvent.click(await screen.findByLabelText("Select Rogue"));
    await userEvent.click(screen.getByLabelText("Select Archmage"));

    await userEvent.selectOptions(screen.getByLabelText("Set rarity for selected"), "rare");

    expect(await screen.findByText(/1 changed/)).toBeInTheDocument();
    expect(screen.getByText(/6 players are wearing it/)).toBeInTheDocument();
  });
});
