import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import BulkToolbar from "./BulkToolbar";

afterEach(() => vi.unstubAllGlobals());

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setup({
  selected = ["c1", "c2"],
  matchingCount = 2,
  preview = { deletable: 2, blocked: [], zones_emptied: [] },
  result = { succeeded: 2, failed: 0, results: [], categories_deleted: [] },
  skills = [{ id: "s1", name: "Packet Whispering" }],
  onClear = () => undefined,
  onSelectAllMatching = () => undefined,
}: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (path: string) => {
    if (String(path).includes("preview-delete")) return json(preview);
    if (String(path).includes("/bulk")) return json(result);
    if (String(path).includes("/admin/skills")) return json(skills);
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <QueryClientProvider client={new QueryClient()}>
      <BulkToolbar
        selected={selected as string[]}
        onClear={onClear as () => void}
        matchingCount={matchingCount as number}
        onSelectAllMatching={onSelectAllMatching as () => void}
      />
    </QueryClientProvider>,
  );
  return fetchMock;
}

function bodyOf(fetchMock: ReturnType<typeof vi.fn>, marker: string) {
  const call = fetchMock.mock.calls.find(([, init]) =>
    String((init as RequestInit)?.body ?? "").includes(marker),
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : null;
}

describe("BulkToolbar", () => {
  it("shows nothing when nothing is selected", () => {
    setup({ selected: [] });

    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("sets state across the selection in one request", async () => {
    const fetchMock = setup();

    await userEvent.selectOptions(screen.getByLabelText("Set state"), "published");

    await waitFor(() => expect(bodyOf(fetchMock, "set_state")).toBeTruthy());
    const body = bodyOf(fetchMock, "set_state");
    expect(body.challenge_ids).toEqual(["c1", "c2"]);
    expect(body.value).toBe("published");
  });

  it("passes a relative XP expression through untouched", async () => {
    const fetchMock = setup();

    await userEvent.type(screen.getByLabelText("Set XP"), "+25");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(bodyOf(fetchMock, "set_xp")).toBeTruthy());
    // The server computes per challenge; the client must not try to resolve it.
    expect(bodyOf(fetchMock, "set_xp").value).toBe("+25");
  });

  it("adds a skill across the selection without replacing what is there", async () => {
    const fetchMock = setup();

    // The skill list is fetched, so wait for the option before picking it.
    await screen.findByRole("option", { name: "Packet Whispering" });
    await userEvent.selectOptions(screen.getByLabelText("Skill"), "Packet Whispering");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(bodyOf(fetchMock, "add_skills")).toBeTruthy());
    // Additive, never "replace" — the server keeps existing mappings.
    expect(bodyOf(fetchMock, "add_skills").value).toEqual(["Packet Whispering"]);
  });

  it("removes a skill across the selection", async () => {
    const fetchMock = setup();

    await screen.findByRole("option", { name: "Packet Whispering" });
    await userEvent.selectOptions(screen.getByLabelText("Skill"), "Packet Whispering");
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(bodyOf(fetchMock, "remove_skills")).toBeTruthy());
    expect(bodyOf(fetchMock, "remove_skills").value).toEqual(["Packet Whispering"]);
  });

  it("clears the schedule when the release field is empty", async () => {
    const fetchMock = setup();

    await userEvent.click(screen.getByRole("button", { name: "Clear schedule" }));

    await waitFor(() => expect(bodyOf(fetchMock, "set_release_at")).toBeTruthy());
    // The other half of setting a wave: null means no schedule.
    expect(bodyOf(fetchMock, "set_release_at").value).toBeNull();
  });

  it("offers to select everything the filter found", async () => {
    const onSelectAllMatching = vi.fn();
    setup({ selected: ["c1"], matchingCount: 47, onSelectAllMatching });

    await userEvent.click(
      screen.getByRole("button", { name: /select all 47 matching/i }),
    );

    expect(onSelectAllMatching).toHaveBeenCalled();
  });

  it("does not offer it when everything matching is already selected", () => {
    setup({ selected: ["c1", "c2"], matchingCount: 2 });

    expect(screen.queryByText(/select all/i)).not.toBeInTheDocument();
  });

  it("names the zone a delete would take with it", async () => {
    setup({
      preview: {
        deletable: 11,
        blocked: [],
        zones_emptied: [
          { category_id: "z1", name: "Networking", skills_orphaned: 6 },
        ],
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Confirm delete" });
    // The consequence that is invisible from the selection itself.
    expect(dialog).toHaveTextContent("This empties Networking");
    expect(dialog).toHaveTextContent("6 skills are kept");
  });

  it("says how many cannot be deleted, and offers to delete the rest", async () => {
    setup({
      preview: {
        deletable: 9,
        blocked: [
          { challenge_id: "c9", ok: false, reason: "3 solved — hide it instead." },
        ],
        zones_emptied: [],
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Confirm delete" });
    expect(dialog).toHaveTextContent("1 cannot be deleted");
    // The button offers the count that will actually go, not the selection size.
    expect(screen.getByRole("button", { name: "Delete 9" })).toBeInTheDocument();
  });

  it("does not delete unless the dialog is confirmed", async () => {
    const fetchMock = setup();

    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));
    await screen.findByRole("alertdialog", { name: "Confirm delete" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // The preview request carries action "delete" too, so the assertion has to
    // be on the URL: nothing may hit the endpoint that actually writes.
    const wrote = fetchMock.mock.calls.some(
      ([path]) =>
        String(path).includes("/bulk") && !String(path).includes("preview-delete"),
    );
    expect(wrote).toBe(false);
  });

  it("reports what actually happened, including a removed area", async () => {
    const onClear = vi.fn();
    setup({
      result: {
        succeeded: 9,
        failed: 1,
        results: [
          { challenge_id: "c9", ok: false, reason: "3 players have solved this." },
        ],
        categories_deleted: ["Networking"],
      },
      onClear,
    });

    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));
    await screen.findByRole("alertdialog", { name: "Confirm delete" });
    await userEvent.click(screen.getByRole("button", { name: /^Delete \d/ }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("9 changed, 1 skipped");
    expect(status).toHaveTextContent("Areas removed: Networking");
    // The reason, not a bare "some failed".
    expect(status).toHaveTextContent("3 players have solved this.");
    // A stale selection is how the next action hits the wrong rows.
    expect(onClear).toHaveBeenCalled();
  });
});
