import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Avatar from "./Avatar";
import AvatarEditor from "./AvatarEditor";
import type { Accessory } from "../api/avatar";
import { me, renderApp, stubFetch } from "../test/utils";

/** The avatar editor and the component it feeds (spec 073 §5, §9). */

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function accessory(overrides: Partial<Accessory> = {}): Accessory {
  return {
    slug: "hood-plain",
    name: "Plain Hood",
    description: "Undyed wool.",
    slot: "head",
    rarity: "common",
    unlocked: true,
    unlock_kind: "always",
    unlock_ref: null,
    anchor_x: 0.5,
    anchor_y: 0.3,
    anchor_scale: 1,
    anchor_rotation: 0,
    ...overrides,
  };
}

const MINE = { source: "sigil", layers: [], description: "A gules shield.", has_photo: false };

function render({
  accessories = [accessory()],
  mine = MINE,
}: { accessories?: Accessory[]; mine?: Record<string, unknown> } = {}) {
  const mock = stubFetch((path, init) => {
    if (path.includes("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/avatar/accessories")) return { status: 200, body: accessories };
    if (init?.method === "PUT" || init?.method === "POST") {
      const sent = JSON.parse(String(init.body ?? "{}"));
      return {
        status: 200,
        body: { ...mine, source: sent.source ?? "sigil", layers: sent.layers ?? [] },
      };
    }
    if (path.includes("/avatar/me")) return { status: 200, body: mine };
    return { status: 200, body: {} };
  });
  renderApp(<AvatarEditor />);
  return mock;
}

function bodyOf(mock: ReturnType<typeof stubFetch>, method: string) {
  const call = mock.mock.calls.find(([, init]) => (init as RequestInit)?.method === method);
  return call ? JSON.parse(String((call[1] as RequestInit).body ?? "{}")) : null;
}

describe("Avatar", () => {
  it("is one image, with no second path to keep in step", () => {
    // It used to branch on `hasAvatar` and draw a coloured initial otherwise.
    // Everyone has a server-rendered avatar now, so there is nothing to branch.
    renderApp(<Avatar userId="u1" displayName="Grix" />);

    const image = screen.getByTitle("Grix");
    expect(image.tagName).toBe("IMG");
    expect(image).toHaveAttribute("src", "/api/users/u1/avatar");
  });

  it("is decorative, because the name is always beside it", () => {
    renderApp(<Avatar userId="u1" displayName="Grix" />);

    // "Grix, Grix" is worse for a screen reader than "Grix".
    expect(screen.getByTitle("Grix")).toHaveAttribute("alt", "");
  });
});

describe("AvatarEditor", () => {
  it("offers what you have unlocked", async () => {
    render();

    expect(await screen.findByRole("button", { name: /Plain Hood/ })).toBeEnabled();
  });

  it("shows a locked accessory, and says what earns it", async () => {
    // Listed rather than withheld: seeing the hat you have not earned is the
    // motivation. The reason is words, never colour alone (spec 048).
    render({
      accessories: [
        accessory({
          slug: "hat-wizard",
          name: "Pointed Hat",
          unlocked: false,
          unlock_kind: "class",
          unlock_ref: "Wizard",
        }),
      ],
    });

    const button = await screen.findByRole("button", { name: /Pointed Hat/ });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Play as Wizard");
  });

  it("equips at the authored anchor rather than the middle", async () => {
    // The anchors are the reason the editor is correction and not composition.
    const mock = render({
      accessories: [accessory({ anchor_x: 0.4, anchor_y: 0.2, anchor_scale: 1.5 })],
    });

    await userEvent.click(await screen.findByRole("button", { name: /Plain Hood/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(bodyOf(mock, "PUT")).toBeTruthy());
    expect(bodyOf(mock, "PUT").layers[0]).toMatchObject({
      accessory: "hood-plain",
      x: 0.4,
      y: 0.2,
      scale: 1.5,
    });
  });

  it("saves the transform, not a flattened image", async () => {
    const mock = render();

    await userEvent.click(await screen.findByRole("button", { name: /Plain Hood/ }));
    // A range input is not typeable; fireEvent is how you move a slider.
    fireEvent.change(screen.getByLabelText("Size"), { target: { value: "2" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(bodyOf(mock, "PUT")).toBeTruthy());
    const layer = bodyOf(mock, "PUT").layers[0];
    // Unlocking a new hat next Tuesday must not lose this fit.
    expect(layer).toHaveProperty("scale");
    expect(layer).toHaveProperty("rotation");
    expect(layer).toHaveProperty("x");
  });

  it("only one thing occupies a slot", async () => {
    const mock = render({
      accessories: [
        accessory(),
        accessory({ slug: "band-leather", name: "Leather Band" }),
      ],
    });

    await userEvent.click(await screen.findByRole("button", { name: /Plain Hood/ }));
    await userEvent.click(screen.getByRole("button", { name: /Leather Band/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(bodyOf(mock, "PUT")).toBeTruthy());
    const layers = bodyOf(mock, "PUT").layers;
    expect(layers).toHaveLength(1);
    expect(layers[0].accessory).toBe("band-leather");
  });

  it("takes something off again", async () => {
    const mock = render();

    await userEvent.click(await screen.findByRole("button", { name: /Plain Hood/ }));
    await userEvent.click(screen.getByRole("button", { name: "Take off" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(bodyOf(mock, "PUT")).toBeTruthy());
    expect(bodyOf(mock, "PUT").layers).toEqual([]);
  });

  it("does not offer the work photo to an account without one", async () => {
    render();
    await screen.findByRole("button", { name: /Plain Hood/ });

    expect(screen.queryByLabelText(/work photo/i)).not.toBeInTheDocument();
  });

  it("offers it to an account that has one", async () => {
    render({ mine: { ...MINE, has_photo: true } });

    expect(await screen.findByLabelText(/work photo/i)).toBeInTheDocument();
  });

  it("describes the crest in words as well as showing it", async () => {
    render();

    expect(await screen.findByText("A gules shield.")).toBeInTheDocument();
  });

  it("starting over clears the layers", async () => {
    const mock = render();

    await userEvent.click(await screen.findByRole("button", { name: /Plain Hood/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start over" }));

    await waitFor(() =>
      expect(
        mock.mock.calls.some(([path]) => String(path).includes("/avatar/me/reset")),
      ).toBe(true),
    );
  });
});
