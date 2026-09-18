import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./SettingsPage";
import * as authApi from "../api/auth";
import ThemeToggle from "../components/ThemeToggle";
import { me, renderApp } from "../test/utils";

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

function signedIn(overrides: Parameters<typeof me>[0] = {}) {
  vi.spyOn(authApi, "getMe").mockResolvedValue(me(overrides));
}

describe("ThemeToggle", () => {
  it("offers dark when the page is light, and light when it is dark", async () => {
    signedIn({ base_theme: "parchment" });
    renderApp(<ThemeToggle />);
    expect(
      await screen.findByRole("button", { name: /switch to the dark theme/i }),
    ).toBeInTheDocument();
  });

  it("switches and paints before the request resolves", async () => {
    signedIn({ base_theme: "parchment" });
    const update = vi
      .spyOn(authApi, "updateTheme")
      .mockImplementation(() => new Promise(() => {}));
    renderApp(<ThemeToggle />);

    await userEvent.click(await screen.findByRole("button", { name: /dark theme/i }));

    // React Query v5 hands mutationFn a context object as a second argument,
    // so assert on the variable rather than the whole call.
    expect(update.mock.calls[0]?.[0]).toBe("dark-dungeon");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark-dungeon");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("reflects the choice underneath while high contrast overrides the page", async () => {
    // The toggle says what it will do. While high contrast is on, that is still
    // about the theme it would return to.
    signedIn({ theme: "high-contrast", high_contrast: true, base_theme: "dark-dungeon" });
    renderApp(<ThemeToggle />);

    expect(
      await screen.findByRole("button", { name: /switch to the light theme/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing when nobody is signed in", async () => {
    vi.spyOn(authApi, "getMe").mockRejectedValue(new Error("401"));
    renderApp(<ThemeToggle />);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /theme/i })).not.toBeInTheDocument(),
    );
  });
});

describe("SettingsPage", () => {
  it("offers light and dark, and no secret themes", async () => {
    signedIn({ base_theme: "parchment" });
    renderApp(<SettingsPage />);

    expect(await screen.findByRole("button", { name: "Parchment" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dark Dungeon" })).toBeInTheDocument();
    for (const secret of ["Purple Squirrel", "DND", "The Mr. Anderson"]) {
      expect(screen.queryByRole("button", { name: secret })).not.toBeInTheDocument();
    }
  });

  it("shows a secret theme once the player holds it, worn or not", async () => {
    // Held, not merely worn (spec 058 §5): a player who earned a theme and
    // toggled back to daylight can still find it.
    signedIn({ base_theme: "parchment", unlocked_themes: ["mr-anderson"] });
    renderApp(<SettingsPage />);

    expect(
      await screen.findByRole("button", { name: /The Mr. Anderson/ }),
    ).toBeInTheDocument();
    // Only the one they hold.
    expect(screen.queryByRole("button", { name: /Purple Squirrel/ })).not.toBeInTheDocument();
  });

  it("selects a held secret theme", async () => {
    signedIn({ base_theme: "parchment", unlocked_themes: ["dnd"] });
    const update = vi.spyOn(authApi, "updateTheme").mockResolvedValue({ message: "ok" });
    renderApp(<SettingsPage />);

    await userEvent.click(await screen.findByRole("button", { name: /DND/ }));

    expect(update).toHaveBeenCalledWith("dnd");
  });

  it("turns high contrast on, overriding the appearance choice", async () => {
    signedIn({ base_theme: "dark-dungeon" });
    const update = vi.spyOn(authApi, "updateHighContrast").mockResolvedValue({ message: "ok" });
    renderApp(<SettingsPage />);

    await userEvent.click(await screen.findByRole("checkbox", { name: /high contrast/i }));

    expect(update.mock.calls[0]?.[0]).toBe(true);
    expect(document.documentElement.getAttribute("data-theme")).toBe("high-contrast");
  });

  it("puts the chosen theme back when high contrast goes off", async () => {
    signedIn({ theme: "high-contrast", high_contrast: true, base_theme: "dark-dungeon" });
    vi.spyOn(authApi, "updateHighContrast").mockResolvedValue({ message: "ok" });
    renderApp(<SettingsPage />);

    await userEvent.click(await screen.findByRole("checkbox", { name: /high contrast/i }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark-dungeon");
  });

  it("says what turning it off will restore", async () => {
    signedIn({ theme: "high-contrast", high_contrast: true, base_theme: "dark-dungeon" });
    renderApp(<SettingsPage />);

    expect(await screen.findByText(/puts back/i)).toHaveTextContent("Dark Dungeon");
  });
});


describe("SettingsPage, the rest of it", () => {
  it("builds the notification list from the kind map", async () => {
    signedIn({});
    renderApp(<SettingsPage />);

    // A tenth kind appears here without this page being touched (070 §4).
    expect(await screen.findByLabelText("Level up")).toBeInTheDocument();
    expect(screen.getByLabelText("Boss kill")).toBeInTheDocument();
    expect(screen.getByLabelText("Announcement")).toBeInTheDocument();
  });

  it("mutes a kind by sending the whole set", async () => {
    signedIn({ muted_notification_kinds: ["dispatch"] });
    const update = vi.spyOn(authApi, "updateMutedKinds").mockResolvedValue({ message: "ok" });
    renderApp(<SettingsPage />);

    await userEvent.click(await screen.findByLabelText("Boss kill"));

    // The whole set, so nobody has to reason about which call left what state.
    expect(update).toHaveBeenCalledWith(["dispatch", "boss_kill"]);
  });

  it("unmutes by sending the set without it", async () => {
    signedIn({ muted_notification_kinds: ["boss_kill", "dispatch"] });
    const update = vi.spyOn(authApi, "updateMutedKinds").mockResolvedValue({ message: "ok" });
    renderApp(<SettingsPage />);

    await userEvent.click(await screen.findByLabelText("Boss kill"));

    expect(update).toHaveBeenCalledWith(["dispatch"]);
  });

  it("says a muted kind is quieter, never absent", async () => {
    signedIn({});
    renderApp(<SettingsPage />);

    expect(
      await screen.findByText(/still arrives and still sits in your inbox/),
    ).toBeInTheDocument();
  });

  it("lets a guest rename themselves", async () => {
    signedIn({ can_rename: true });
    const update = vi.spyOn(authApi, "updateDisplayName").mockResolvedValue({} as never);
    renderApp(<SettingsPage />);

    await userEvent.clear(await screen.findByLabelText("Display name"));
    await userEvent.type(screen.getByLabelText("Display name"), "Grix the Bold");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(update).toHaveBeenCalledWith("Grix the Bold");
  });

  it("does not offer a directory account a field it cannot keep", async () => {
    signedIn({ can_rename: false });
    renderApp(<SettingsPage />);

    // identity.py rewrites the name on every sign-in, so the field would tell
    // somebody it saved and then revert them (spec 070 §3).
    expect(await screen.findByText(/comes from your work account/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Display name")).not.toBeInTheDocument();
  });

  it("offers the tour again", async () => {
    signedIn({});
    renderApp(<SettingsPage />);

    expect(await screen.findByRole("button", { name: "Show the tour" })).toBeInTheDocument();
  });
});
