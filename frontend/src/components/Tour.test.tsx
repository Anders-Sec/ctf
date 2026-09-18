import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Tour, { openTour } from "./Tour";

beforeEach(() => {
  localStorage.clear();
});

describe("Tour", () => {
  it("shows on a first visit", async () => {
    render(<Tour />);

    expect(await screen.findByRole("dialog", { name: /Your inbox/ })).toBeInTheDocument();
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
  });

  it("does not show again once it has been seen", () => {
    localStorage.setItem("ctf.tour.seen", "1");

    render(<Tour />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("walks four stops and remembers finishing", async () => {
    render(<Tour />);

    for (let step = 1; step < 4; step += 1) {
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    expect(screen.getByText("4 of 4")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem("ctf.tour.seen")).toBe("1");
  });

  it("is skippable at every step, and remembers the skip", async () => {
    render(<Tour />);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    // Skippable partway through, not only on the first stop.
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem("ctf.tour.seen")).toBe("1");
  });

  it("closes on Escape", async () => {
    render(<Tour />);
    await screen.findByRole("dialog");

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("can be reopened after being dismissed", async () => {
    // Dismissing is not a one-way door: the profile menu calls openTour()
    // (spec 066 §3.2).
    localStorage.setItem("ctf.tour.seen", "1");
    render(<Tour />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openTour();

    expect(await screen.findByRole("dialog", { name: /Your inbox/ })).toBeInTheDocument();
  });

  it("treats blocked storage as seen rather than showing on every load", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    render(<Tour />);

    // Showing a tour on every single page load would be worse than never.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    getItem.mockRestore();
  });

  it("spotlights the real element rather than describing it", () => {
    // §3.2 asked for callouts *on the nav*. The first build was a centred
    // dialog that described it without pointing at anything.
    const target = document.createElement("button");
    target.setAttribute("data-tour", "inbox");
    document.body.appendChild(target);

    const { container } = render(<Tour />);

    const ring = container.querySelector("[class*='ring-accent']");
    expect(ring).not.toBeNull();
    target.remove();
  });

  it("moves the spotlight as the stops advance", async () => {
    const inbox = document.createElement("button");
    inbox.setAttribute("data-tour", "inbox");
    const board = document.createElement("a");
    board.setAttribute("data-tour", "board");
    document.body.append(inbox, board);

    render(<Tour />);
    expect(screen.getByRole("dialog", { name: /Your inbox/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.getByRole("dialog", { name: /The board/ })).toBeInTheDocument();
    inbox.remove();
    board.remove();
  });

  it("still shows itself on a page with none of its targets", () => {
    // A page without the nav should show the tour centred rather than point
    // confidently at nothing.
    const { container } = render(<Tour />);

    expect(screen.getByRole("dialog", { name: /Your inbox/ })).toBeInTheDocument();
    expect(container.querySelector("[class*='ring-accent']")).toBeNull();
  });

  it("can go back", async () => {
    render(<Tour />);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("dialog", { name: /Your inbox/ })).toBeInTheDocument();
  });

  it("offers no Back on the first stop", () => {
    render(<Tour />);

    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });
});
