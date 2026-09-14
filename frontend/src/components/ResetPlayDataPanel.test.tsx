import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ResetPlayDataPanel from "./ResetPlayDataPanel";

afterEach(() => vi.unstubAllGlobals());

const GROUPS = [
  { group: "solves", label: "Solves", rows: 1204 },
  { group: "submissions", label: "Flag submissions", rows: 8391 },
  { group: "loot", label: "Loot boxes", rows: 12 },
];

function setup(canWrite = true) {
  const fetchMock = vi.fn(async (path: string) => {
    const body = String(path).includes("reset-play-data")
      ? { deleted: { solve: 1204 }, total: 1204 }
      : GROUPS;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ResetPlayDataPanel canWrite={canWrite} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

function wrote(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.find(([path]) =>
    String(path).includes("reset-play-data"),
  );
}

describe("ResetPlayDataPanel", () => {
  it("shows nothing to a read-only viewer", () => {
    setup(false);

    expect(screen.queryByText("Reset play data")).not.toBeInTheDocument();
  });

  it("shows how much each group holds", async () => {
    setup();

    expect(await screen.findByText("Solves")).toBeInTheDocument();
    expect(screen.getByText("1,204")).toBeInTheDocument();
    expect(screen.getByText("8,391")).toBeInTheDocument();
  });

  it("totals only the groups that are ticked", async () => {
    setup();

    await userEvent.click(await screen.findByRole("checkbox", { name: /Solves/ }));

    // 1,204 — not the 9,607 across every group.
    expect(screen.getByText("1,204", { selector: "strong" })).toBeInTheDocument();
  });

  it("will not fire until RESET is typed", async () => {
    const fetchMock = setup();

    await userEvent.click(await screen.findByRole("checkbox", { name: /Solves/ }));
    const button = screen.getByRole("button", { name: "Reset play data" });
    expect(button).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "reset");
    expect(button).toBeDisabled();

    await userEvent.clear(screen.getByLabelText("Type RESET to confirm"));
    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "RESET");
    expect(button).toBeEnabled();
    expect(wrote(fetchMock)).toBeUndefined();
  });

  it("sends only the chosen groups", async () => {
    const fetchMock = setup();

    await userEvent.click(await screen.findByRole("checkbox", { name: /Solves/ }));
    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "RESET");
    await userEvent.click(screen.getByRole("button", { name: "Reset play data" }));

    await waitFor(() => expect(wrote(fetchMock)).toBeTruthy());
    const body = JSON.parse(String((wrote(fetchMock)![1] as RequestInit).body));
    expect(body.groups).toEqual(["solves"]);
  });

  it("can take everything at once", async () => {
    const fetchMock = setup();

    await userEvent.click(await screen.findByRole("button", { name: "Select everything" }));
    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "RESET");
    await userEvent.click(screen.getByRole("button", { name: "Reset play data" }));

    await waitFor(() => expect(wrote(fetchMock)).toBeTruthy());
    const body = JSON.parse(String((wrote(fetchMock)![1] as RequestInit).body));
    expect(body.groups).toEqual(["solves", "submissions", "loot"]);
  });

  it("reports how much went", async () => {
    setup();

    await userEvent.click(await screen.findByRole("checkbox", { name: /Solves/ }));
    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "RESET");
    await userEvent.click(screen.getByRole("button", { name: "Reset play data" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Cleared 1,204 rows");
  });
});
