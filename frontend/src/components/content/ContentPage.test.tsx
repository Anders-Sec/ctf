import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ContentBulkBar,
  ContentDrawer,
  ContentGroupList,
  type ContentGroup,
} from "./ContentPage";

beforeEach(() => {
  window.localStorage.clear();
});

function groups(): ContentGroup[] {
  return [
    {
      id: "web",
      heading: "Web Attacks",
      summary: "2 skills · 1 funny",
      count: 2,
      rows: (
        <ul>
          <li>Injection Artistry</li>
          <li>Auth Bypass</li>
        </ul>
      ),
    },
    {
      id: "crypto",
      heading: "Crypto",
      summary: "0 skills",
      count: 0,
      rows: <ul />,
    },
  ];
}

describe("ContentGroupList", () => {
  it("renders a populated group and skips an empty one", () => {
    render(<ContentGroupList groups={groups()} storageKey="test" empty="Nothing." />);

    expect(screen.getByText("Web Attacks")).toBeInTheDocument();
    // An empty group is noise, not information.
    expect(screen.queryByText("Crypto")).not.toBeInTheDocument();
  });

  it("collapses a group, keeping its summary visible", async () => {
    render(<ContentGroupList groups={groups()} storageKey="test" empty="Nothing." />);

    await userEvent.click(screen.getByRole("button", { expanded: true }));

    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
    // What makes collapsing safe: a shut group still says what is inside it.
    expect(screen.getByText("2 skills · 1 funny")).toBeInTheDocument();
  });

  it("remembers the collapsed set across a remount", async () => {
    const { unmount } = render(
      <ContentGroupList groups={groups()} storageKey="test" empty="Nothing." />,
    );
    await userEvent.click(screen.getByRole("button", { expanded: true }));
    unmount();

    render(<ContentGroupList groups={groups()} storageKey="test" empty="Nothing." />);

    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
  });

  it("survives storage it cannot read", () => {
    const get = vi
      .spyOn(window.localStorage, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });

    // A collapse we cannot remember still has to render.
    render(<ContentGroupList groups={groups()} storageKey="test" empty="Nothing." />);
    expect(screen.getByText("Injection Artistry")).toBeInTheDocument();

    get.mockRestore();
  });

  it("says so when every group is empty", () => {
    render(
      <ContentGroupList
        groups={[{ id: "a", heading: "A", summary: "", count: 0, rows: <ul /> }]}
        storageKey="test"
        empty="Nothing matches that."
      />,
    );

    expect(screen.getByText("Nothing matches that.")).toBeInTheDocument();
  });
});

describe("ContentDrawer", () => {
  it("closes straight away when nothing is unsaved", async () => {
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty={false} onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Close editor" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("asks before discarding an edit", async () => {
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Close editor" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Close without saving?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the edit when the admin says to", async () => {
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Close editor" }));
    await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText("Close without saving?")).not.toBeInTheDocument();
  });

  it("asks on Escape too, reading the current dirty state", async () => {
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Close without saving?")).toBeInTheDocument();
  });

  it("marks an unsaved drawer", () => {
    render(
      <ContentDrawer title="Injection" dirty onClose={vi.fn()} footer={null}>
        body
      </ContentDrawer>,
    );

    expect(screen.getByText("unsaved")).toBeInTheDocument();
  });

  it("puts delete in the header, disabled with a reason when refused", () => {
    render(
      <ContentDrawer
        title="First Blood"
        dirty={false}
        onClose={vi.fn()}
        onDelete={vi.fn()}
        deleteDisabled
        deleteTitle="Players hold this."
        footer={null}
      >
        body
      </ContentDrawer>,
    );

    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Players hold this.");
  });
});

describe("ContentBulkBar", () => {
  it("stays out of the way with nothing selected", () => {
    const { container } = render(
      <ContentBulkBar count={0} onClear={vi.fn()}>
        <button type="button">Delete</button>
      </ContentBulkBar>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names the operations the page declared", () => {
    render(
      <ContentBulkBar count={3} onClear={vi.fn()}>
        <button type="button">Set kind</button>
      </ContentBulkBar>,
    );

    const bar = screen.getByRole("group", { name: "Bulk actions" });
    expect(within(bar).getByText("3 selected")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Set kind" })).toBeInTheDocument();
  });

  it("reports a partial failure with its reasons rather than a bare success", () => {
    render(
      <ContentBulkBar
        count={0}
        onClear={vi.fn()}
        result={{ changed: 2, refused: { a: "3 players hold it", b: "3 players hold it" } }}
      >
        <span />
      </ContentBulkBar>,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("2 changed");
    expect(status).toHaveTextContent("2 refused");
    // Deduplicated: the same reason twice reads as two problems.
    expect(status.textContent?.match(/3 players hold it/g)).toHaveLength(1);
  });
});

describe("ContentDrawer focus (spec 071)", () => {
  it("moves focus into the drawer", async () => {
    render(
      <ContentDrawer title="Injection" dirty={false} onClose={vi.fn()} footer={null}>
        body
      </ContentDrawer>,
    );

    const panel = screen.getByRole("dialog", { name: "Edit Injection" });
    expect(panel).toContainElement(document.activeElement as HTMLElement);
  });

  it("Escape still refuses to discard unsaved work", async () => {
    // The hand-rolled handler needed a *missing* dependency array to avoid
    // closing over a stale `dirty`. The hook calls the current callback, so the
    // guard holds without that trick.
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Close without saving?")).toBeInTheDocument();
  });

  it("Escape closes when there is nothing to lose", async () => {
    const onClose = vi.fn();
    render(
      <ContentDrawer title="Injection" dirty={false} onClose={onClose} footer={null}>
        body
      </ContentDrawer>,
    );

    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });
});
