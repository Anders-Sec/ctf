import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./LoginPage";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Signed out: /auth/me answers 401, which is an answer rather than a failure. */
function signedOut(extra?: (path: string) => { status: number; body: unknown } | undefined) {
  return stubFetch((path) => {
    const handled = extra?.(path);
    if (handled) return handled;
    if (path.endsWith("/auth/me")) {
      return { status: 401, body: { error: { code: "not_authenticated", message: "no" } } };
    }
    return { status: 200, body: {} };
  });
}

describe("LoginPage", () => {
  it("offers both doors into the platform", async () => {
    signedOut();
    renderApp(<LoginPage />, { route: "/login" });

    expect(await screen.findByRole("button", { name: /work account/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
  });

  it("confirms a magic link request without confirming the address exists", async () => {
    // The API answers identically for known and unknown addresses; this screen
    // must not undo that by wording the two cases differently.
    const fetchMock = signedOut((path) =>
      path.endsWith("/auth/magic-link") ? { status: 202, body: { message: "ok" } } : undefined,
    );
    renderApp(<LoginPage />, { route: "/login" });

    await userEvent.type(await screen.findByLabelText(/email address/i), "guest@example.com");
    await userEvent.click(screen.getByRole("button", { name: /email me a sign-in link/i }));

    expect(await screen.findByText(/if that address can sign in/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/magic-link",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("lets the player correct a mistyped address", async () => {
    signedOut((path) =>
      path.endsWith("/auth/magic-link") ? { status: 202, body: { message: "ok" } } : undefined,
    );
    renderApp(<LoginPage />, { route: "/login" });

    await userEvent.type(await screen.findByLabelText(/email address/i), "typo@example.com");
    await userEvent.click(screen.getByRole("button", { name: /email me a sign-in link/i }));
    await userEvent.click(await screen.findByRole("button", { name: /different address/i }));

    expect(await screen.findByLabelText(/email address/i)).toBeInTheDocument();
  });

  it("reports a failed provider sign-in without blaming the player", async () => {
    signedOut();
    renderApp(<LoginPage />, { route: "/login?error=entra_failed" });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/did not complete/i),
    );
  });
});
