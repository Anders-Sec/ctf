import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as authApi from "../api/auth";
import { THEME_STORAGE_KEY } from "../theme/apply";
import { me, renderApp } from "../test/utils";
import ThemePicker from "./ThemePicker";

function signedIn(overrides: Parameters<typeof me>[0] = {}) {
  vi.spyOn(authApi, "getMe").mockResolvedValue(me(overrides));
}

describe("ThemePicker", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("offers every preset in the roster", async () => {
    signedIn();
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));

    for (const label of ["Parchment", "Dark Dungeon", "Torchlight", "High Contrast"]) {
      expect(screen.getByRole("menuitemradio", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("stamps the document immediately rather than waiting on the request", async () => {
    // A theme switch that waits on a round-trip feels broken. The session
    // refetch puts back whatever the server actually holds if this was wrong.
    signedIn();
    const update = vi
      .spyOn(authApi, "updateTheme")
      .mockImplementation(() => new Promise(() => {}));
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Dark Dungeon/ }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark-dungeon");
    expect(update).toHaveBeenCalledWith("dark-dungeon");
  });

  it("caches the choice, so the next cold load does not flash", async () => {
    signedIn();
    vi.spyOn(authApi, "updateTheme").mockResolvedValue({ message: "ok" });
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Torchlight/ }));

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("torchlight");
  });

  it("sets colour-scheme so native controls follow the theme", async () => {
    signedIn();
    vi.spyOn(authApi, "updateTheme").mockResolvedValue({ message: "ok" });
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Dark Dungeon/ }));

    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("says when the player is following the event default", async () => {
    signedIn({ theme: "dark-dungeon", theme_source: "event" });
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));

    expect(screen.getByText("Following the event default.")).toBeInTheDocument();
    // Nothing to clear yet — offering it would clear a preference that does
    // not exist.
    expect(
      screen.queryByRole("menuitem", { name: "Follow the event default" }),
    ).not.toBeInTheDocument();
  });

  it("offers a way back to the default once they have chosen", async () => {
    signedIn({ theme: "torchlight", theme_source: "user" });
    const update = vi.spyOn(authApi, "updateTheme").mockResolvedValue({ message: "ok" });
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Follow the event default" }));

    expect(update).toHaveBeenCalledWith(null);
  });

  it("marks the current theme for a screen reader, not by colour alone", async () => {
    signedIn({ theme: "torchlight", theme_source: "user" });
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));

    expect(screen.getByRole("menuitemradio", { name: /Torchlight/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("menuitemradio", { name: /Parchment/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("closes on Escape", async () => {
    signedIn();
    renderApp(<ThemePicker />);

    await userEvent.click(await screen.findByRole("button", { name: "Theme" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("renders nothing when nobody is signed in", async () => {
    vi.spyOn(authApi, "getMe").mockRejectedValue(new Error("401"));
    renderApp(<ThemePicker />);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Theme" })).not.toBeInTheDocument(),
    );
  });
});
