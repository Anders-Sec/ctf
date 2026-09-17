import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminAchievementsPage from "./AdminAchievementsPage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  window.localStorage.clear();
});

const ROSTER = [
  {
    id: "a1",
    code: "first_blood",
    name: "First Blood",
    description: "You drew it first.",
    earned_by: "Solve any challenge",
    display_order: 0,
    secret: false,
    has_trigger: true,
    needs_copy: false,
    held_by: 12,
    loot_box_type: "adventurer",
    loot_rarity: "bronze",
    no_loot_line: null,
    unlocks_theme: null,
  },
  {
    id: "a2",
    code: "ghost_in_the_shell",
    name: "Ghost in the Shell",
    description: "TODO",
    earned_by: "",
    display_order: 1,
    secret: true,
    has_trigger: false,
    needs_copy: true,
    held_by: 0,
    loot_box_type: null,
    loot_rarity: null,
    no_loot_line: null,
    unlocks_theme: null,
  },
];

const TRIGGERS = {
  registered: ["first_blood", "night_owl"],
  unused: ["night_owl"],
  families: [],
};

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.endsWith("/admin/achievements/triggers")) {
      return { status: 200, body: TRIGGERS };
    }
    if (path.endsWith("/admin/achievements/bulk")) {
      return { status: 200, body: { changed: 1, refused: { a1: "12 players hold it" } } };
    }
    if (path.endsWith("/admin/achievements")) {
      if (init?.method === "POST") {
        return {
          status: 201,
          body: {
            id: "a9",
            has_trigger: true,
            needs_copy: false,
            held_by: 0,
            ...JSON.parse(String(init.body)),
          },
        };
      }
      return { status: 200, body: ROSTER };
    }
    if (path.includes("/admin/achievements/") && init?.method === "PATCH") {
      return { status: 200, body: { ...ROSTER[0], ...JSON.parse(String(init.body)) } };
    }
    if (path.includes("/admin/achievements/") && init?.method === "DELETE") {
      return { status: 200, body: { message: "Achievement removed." } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminAchievementsPage />);
  return mock;
}

describe("AdminAchievementsPage", () => {
  it("groups by loot box, with (no loot) last", async () => {
    render();
    await screen.findByText("First Blood");

    const groups = screen
      .getAllByRole("button", { expanded: true })
      .map((heading) => heading.textContent ?? "");
    expect(groups.some((text) => text.includes("adventurer"))).toBe(true);
    expect(groups.findIndex((text) => text.includes("adventurer"))).toBeLessThan(
      groups.findIndex((text) => text.includes("(no loot)")),
    );
    expect(screen.getByText(/1 achievement · 1 need copy · 1 inert/)).toBeInTheDocument();
  });

  it("marks an inert row in the list, where finding out still helps", async () => {
    render();
    await screen.findByText("Ghost in the Shell");

    const row = screen.getByText("Ghost in the Shell").closest("li") as HTMLElement;
    // No trigger is registered for the code, so it will never fire.
    expect(within(row).getByText("no trigger")).toBeInTheDocument();
    expect(within(row).getByText("needs copy")).toBeInTheDocument();
    expect(within(row).getByText("secret")).toBeInTheDocument();
  });

  it("filters down to the rows still needing copy", async () => {
    render();
    await screen.findByText("First Blood");

    // The group header summary says "1 need copy" too, so anchor on the count.
    await userEvent.click(screen.getByRole("button", { name: "1 need copy" }));

    expect(screen.getByText("Ghost in the Shell")).toBeInTheDocument();
    expect(screen.queryByText("First Blood")).not.toBeInTheDocument();
  });

  it("counts the ones that pay nothing and say nothing about it", async () => {
    render();
    await screen.findByText("First Blood");

    await userEvent.click(
      screen.getByRole("button", { name: /pay nothing, say nothing/ }),
    );

    expect(screen.getByText("Ghost in the Shell")).toBeInTheDocument();
    expect(screen.queryByText("First Blood")).not.toBeInTheDocument();
  });

  it("searches by code as well as name", async () => {
    render();
    await screen.findByText("First Blood");

    await userEvent.type(screen.getByLabelText("Search achievements"), "ghost_in");

    expect(screen.getByText("Ghost in the Shell")).toBeInTheDocument();
    expect(screen.queryByText("First Blood")).not.toBeInTheDocument();
  });

  it("edits the reward, which was reachable from nowhere", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Ghost in the Shell"));

    const drawer = screen.getByRole("dialog");
    await userEvent.selectOptions(within(drawer).getByLabelText("Loot box type"), "boss");
    await userEvent.selectOptions(within(drawer).getByLabelText("Loot rarity"), "gold");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/achievements/a2") && init?.method === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        loot_box_type: "boss",
        loot_rarity: "gold",
      });
    });
  });

  it("attaches a secret theme, and offers only the secret ones", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Ghost in the Shell"));

    const picker = within(screen.getByRole("dialog")).getByLabelText("Unlocks theme");
    // Granting somebody Parchment is not a reward.
    expect(within(picker).queryByRole("option", { name: "Parchment" })).toBeNull();
    expect(within(picker).getByRole("option", { name: "The Mr. Anderson" })).toBeInTheDocument();

    await userEvent.selectOptions(picker, "mr-anderson");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/achievements/a2") && init?.method === "PATCH",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        unlocks_theme: "mr-anderson",
      });
    });
  });

  it("clears a reward with an explicit flag, since a PATCH cannot send null", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("First Blood"));

    const drawer = screen.getByRole("dialog");
    await userEvent.selectOptions(within(drawer).getByLabelText("Loot box type"), "");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/achievements/a1") && init?.method === "PATCH",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ clear_loot: true });
    });
  });

  it("leaves the code uneditable on an existing row", async () => {
    render();
    await userEvent.click(await screen.findByText("First Blood"));

    // It joins to a trigger and to every award already granted (spec 030).
    expect(screen.queryByLabelText("Achievement code")).not.toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("first_blood")).toBeInTheDocument();
  });

  it("offers unused trigger codes when creating one", async () => {
    render();
    await userEvent.click(await screen.findByRole("button", { name: "+ New achievement" }));

    const input = screen.getByLabelText("Achievement code");
    expect(input).toHaveAttribute("list", "unused-triggers");
    // The useful new achievement is nearly always one whose trigger exists.
    expect(document.querySelector('#unused-triggers option[value="night_owl"]')).toBeTruthy();
  });

  it("creates one", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByRole("button", { name: "+ New achievement" }));

    const drawer = screen.getByRole("dialog");
    await userEvent.type(within(drawer).getByLabelText("Achievement code"), "night_owl");
    await userEvent.type(within(drawer).getByLabelText("Achievement name"), "Night Owl");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/achievements") && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        code: "night_owl",
        name: "Night Owl",
      });
    });
  });

  it("will not let a held achievement be deleted", async () => {
    render();
    await userEvent.click(await screen.findByText("First Blood"));

    // Taking one back from somebody who earned it is worse than a bad name.
    expect(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    ).toBeDisabled();
  });

  it("allows deleting one nobody holds", async () => {
    const fetchMock = render();
    await userEvent.click(await screen.findByText("Ghost in the Shell"));

    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/admin/achievements/a2") && init?.method === "DELETE",
      );
      expect(call).toBeTruthy();
    });
  });

  it("reports a refused bulk delete per item", async () => {
    render();
    await userEvent.click(await screen.findByLabelText("Select First Blood"));
    await userEvent.click(screen.getByLabelText("Select Ghost in the Shell"));

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/1 changed/)).toBeInTheDocument();
    expect(screen.getByText(/12 players hold it/)).toBeInTheDocument();
  });
});
