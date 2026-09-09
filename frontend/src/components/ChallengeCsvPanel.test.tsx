import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ChallengeCsvPanel from "./ChallengeCsvPanel";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const CLEAN = { created: 3, updated: 1, skipped: 238, dry_run: true, errors: [] };

const REFUSED = {
  created: 0,
  updated: 0,
  skipped: 0,
  dry_run: false,
  errors: [
    { row: 17, column: "difficulty", problem: "'impossible' is not one of: ..." },
  ],
};

function pick(name = "plan.csv") {
  return new File(["category,title,difficulty\n"], name, { type: "text/csv" });
}

describe("ChallengeCsvPanel", () => {
  it("offers the template and the export as direct downloads", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    renderApp(<ChallengeCsvPanel />);

    // Links, not fetches: the browser saves from Content-Disposition.
    expect(screen.getByRole("link", { name: "Download template" })).toHaveAttribute(
      "href",
      "/api/admin/challenges/template.csv",
    );
    expect(screen.getByRole("link", { name: "Export current" })).toHaveAttribute(
      "href",
      "/api/admin/challenges/export.csv",
    );
  });

  it("checks a file without writing by default", async () => {
    const fetchMock = stubFetch(() => ({ status: 200, body: CLEAN }));
    renderApp(<ChallengeCsvPanel />);

    await userEvent.upload(screen.getByLabelText("CSV file"), pick());
    await userEvent.click(screen.getByRole("button", { name: "Check file" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).includes("/admin/challenges/import"),
      );
      // Dry run is the default, so a mistyped file cannot land by accident.
      expect(String(call?.[0])).toContain("dry_run=true");
    });
    expect(await screen.findByText(/would create/i)).toBeInTheDocument();
  });

  it("imports for real once the dry run is unticked", async () => {
    const fetchMock = stubFetch(() => ({
      status: 200,
      body: { ...CLEAN, dry_run: false },
    }));
    renderApp(<ChallengeCsvPanel />);

    await userEvent.upload(screen.getByLabelText("CSV file"), pick());
    await userEvent.click(screen.getByLabelText(/dry run/i));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).includes("/admin/challenges/import"),
      );
      expect(String(call?.[0])).toContain("dry_run=false");
    });
  });

  it("shows which row and column were wrong", async () => {
    stubFetch(() => ({ status: 200, body: REFUSED }));
    renderApp(<ChallengeCsvPanel />);

    await userEvent.upload(screen.getByLabelText("CSV file"), pick());
    await userEvent.click(screen.getByRole("button", { name: "Check file" }));

    // "Invalid difficulty" alone in a 242-row file tells an admin nothing.
    expect(await screen.findByText("17")).toBeInTheDocument();
    expect(screen.getByText("difficulty")).toBeInTheDocument();
    expect(screen.getByText(/nothing was written/i)).toBeInTheDocument();
  });

  it("will not submit without a file", () => {
    stubFetch(() => ({ status: 200, body: {} }));
    renderApp(<ChallengeCsvPanel />);

    expect(screen.getByRole("button", { name: "Check file" })).toBeDisabled();
  });
});
