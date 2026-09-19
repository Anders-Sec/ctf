import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import PortraitBuilder from "./PortraitBuilder";
import type { Builder } from "../api/portraits";
import { me, renderApp, stubFetch } from "../test/utils";

/** The portrait builder (spec 074 §2, §7, §8). */

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const AXES = [
  {
    axis: "ancestry" as const,
    options: [
      { key: "elf", label: "Elf" },
      { key: "dwarf", label: "Dwarf" },
    ],
  },
  {
    axis: "class_look" as const,
    options: [
      { key: "wizard", label: "Wizard" },
      { key: "rogue", label: "Rogue" },
    ],
  },
  {
    axis: "art_style" as const,
    options: [{ key: "oil", label: "Oil Painting" }],
  },
];

function builder(overrides: Partial<Builder> = {}): Builder {
  return {
    available: true,
    remaining: 3,
    candidates_per_job: 2,
    default_class_look: null,
    class_locked_note: null,
    axes: AXES,
    ...overrides,
  };
}

const JOB = {
  id: "j1",
  state: "done",
  error: null,
  chosen_candidate_id: null,
  candidates: [
    { id: "c1", seed: 111 },
    { id: "c2", seed: 222 },
  ],
};

function render({
  config = builder(),
  jobs = [] as unknown[],
  job = JOB as unknown,
  chosen = null as unknown,
}: Record<string, unknown> = {}) {
  const mock = stubFetch((path, init) => {
    if (path.includes("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/portraits/builder")) return { status: 200, body: config };
    // Choosing returns the whole grid with the pick marked, not just the pick.
    if (init?.method === "POST" && path.includes("/choose")) {
      return { status: 200, body: chosen ?? job };
    }
    if (init?.method === "POST") return { status: 202, body: job };
    if (path.includes("/portraits/jobs")) return { status: 200, body: jobs };
    return { status: 200, body: {} };
  });
  renderApp(<PortraitBuilder />);
  return mock;
}

function bodyOf(mock: ReturnType<typeof stubFetch>) {
  const call = mock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
  return call ? JSON.parse(String((call[1] as RequestInit).body ?? "{}")) : null;
}

describe("PortraitBuilder", () => {
  it("is not rendered at all when the host is dark", async () => {
    // Spec 074 §7: absent, not present and failing. Everything spec 073 built
    // carries on regardless.
    render({ config: builder({ available: false }) });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Paint it" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(/have one painted/i)).not.toBeInTheDocument();
  });

  it("offers every axis the server sent", async () => {
    render();

    expect(await screen.findByLabelText("Ancestry")).toBeInTheDocument();
    expect(screen.getByLabelText("Class")).toBeInTheDocument();
    expect(screen.getByLabelText("Style")).toBeInTheDocument();
  });

  it("has no text box anywhere", async () => {
    // The single largest decision in spec 074, asserted directly: Turbo ignores
    // negative prompts, so the input vocabulary has to be the filter. A text
    // box appearing here later would quietly undo that.
    render();
    await screen.findByLabelText("Ancestry");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(document.querySelectorAll("textarea")).toHaveLength(0);
    expect(document.querySelectorAll('input[type="text"]')).toHaveLength(0);
  });

  it("sends keys, never labels", async () => {
    const mock = render();
    await screen.findByLabelText("Ancestry");

    await userEvent.selectOptions(screen.getByLabelText("Ancestry"), "dwarf");
    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    await waitFor(() => expect(bodyOf(mock)).toBeTruthy());
    expect(bodyOf(mock).traits).toEqual({ ancestry: "dwarf" });
  });

  it("leaves an unset axis out rather than guessing", async () => {
    const mock = render();
    await screen.findByLabelText("Ancestry");

    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    await waitFor(() => expect(bodyOf(mock)).toBeTruthy());
    expect(bodyOf(mock).traits).toEqual({});
  });

  it("pre-selects your own class", async () => {
    // What ties a portrait to progression rather than to a costume box.
    render({ config: builder({ default_class_look: "rogue" }) });

    await waitFor(() => expect(screen.getByLabelText("Class")).toHaveValue("rogue"));
  });

  it("surprise me fills every axis", async () => {
    const mock = render();
    await screen.findByLabelText("Ancestry");

    await userEvent.click(screen.getByRole("button", { name: "Surprise me" }));
    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    await waitFor(() => expect(bodyOf(mock)).toBeTruthy());
    expect(Object.keys(bodyOf(mock).traits).sort()).toEqual([
      "ancestry",
      "art_style",
      "class_look",
    ]);
  });

  it("shows the grid to choose from", async () => {
    render();
    await screen.findByLabelText("Ancestry");

    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    expect(await screen.findByRole("button", { name: "Use portrait 111" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use portrait 222" })).toBeInTheDocument();
  });

  it("adopts the one you pick", async () => {
    const mock = render();
    await screen.findByLabelText("Ancestry");
    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    await userEvent.click(await screen.findByRole("button", { name: "Use portrait 222" }));

    await waitFor(() =>
      expect(
        mock.mock.calls.some(([path]) =>
          String(path).includes("/portraits/candidates/c2/choose"),
        ),
      ).toBe(true),
    );
  });

  it("stops offering to paint when the budget is gone", async () => {
    render({ config: builder({ remaining: 0 }) });

    expect(await screen.findByRole("button", { name: "Paint it" })).toBeDisabled();
    expect(screen.getByText(/loot grants more/i)).toBeInTheDocument();
  });

  it("says a failed job did not come out, rather than blaming the host", async () => {
    render({ job: { id: "j2", state: "failed", error: "rejected", candidates: [] } });
    await screen.findByLabelText("Ancestry");

    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/try different choices/i);
  });

  it("finds an earlier grid again after a reload", async () => {
    render({ jobs: [JOB] });

    expect(await screen.findByRole("button", { name: "Use portrait 111" })).toBeInTheDocument();
  });
});

describe("PortraitBuilder — the grid stays (spec 074 §11.1)", () => {
  it("keeps all four after you pick one", async () => {
    // It used to clear the grid the moment you chose, so changing your mind
    // cost another generation.
    render({
      job: { ...JOB, chosen_candidate_id: null },
      chosen: { ...JOB, chosen_candidate_id: "c1" },
    });
    await screen.findByLabelText("Ancestry");
    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));
    await screen.findByRole("button", { name: "Use portrait 111" });

    await userEvent.click(screen.getByRole("button", { name: "Use portrait 111" }));

    expect(
      await screen.findByRole("button", { name: "Portrait 111, currently yours" }),
    ).toBeInTheDocument();
    // The other one is still there to change to.
    expect(screen.getByRole("button", { name: "Use portrait 222" })).toBeInTheDocument();
  });

  it("marks the live one in words, not only with a border", async () => {
    render({
      job: { ...JOB, chosen_candidate_id: null },
      chosen: { ...JOB, chosen_candidate_id: "c2" },
    });
    await screen.findByLabelText("Ancestry");
    await userEvent.click(screen.getByRole("button", { name: "Paint it" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Use portrait 222" }),
    );

    const live = await screen.findByRole("button", {
      name: "Portrait 222, currently yours",
    });
    expect(live).toHaveAttribute("aria-pressed", "true");
    expect(live).toHaveTextContent("Yours");
  });
});

describe("PortraitBuilder — budget and gating", () => {
  it("says Unlimited for an admin rather than a number", async () => {
    render({ config: builder({ remaining: null }) });

    expect(await screen.findByText(/Unlimited/)).toBeInTheDocument();
  });

  it("still lets an admin paint", async () => {
    render({ config: builder({ remaining: null }) });

    expect(await screen.findByRole("button", { name: "Paint it" })).toBeEnabled();
  });

  it("explains an empty Class axis instead of showing a dead dropdown", async () => {
    render({
      config: builder({
        axes: [{ axis: "class_look" as const, options: [] }],
        class_locked_note: "Reach level 5 to choose a class.",
      }),
    });

    expect(await screen.findByText("Reach level 5 to choose a class.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Class")).not.toBeInTheDocument();
  });
});
