import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useDialogFocus } from "./useDialogFocus";

/**
 * The hook's own tests (spec 071 §6).
 *
 * A shared hook is worth exactly as much as its weakest caller, so the per-
 * dialog tests live with their dialogs. These pin the behaviour every one of
 * them inherits.
 */

function Dialog({
  onClose,
  trap = true,
  empty = false,
}: {
  onClose?: () => void;
  trap?: boolean;
  empty?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(panel, { onClose, trap });

  return (
    <div ref={panel} tabIndex={-1} role="dialog" aria-label="Test dialog">
      {!empty && (
        <>
          <button type="button">First</button>
          <input aria-label="Middle" />
          <button type="button">Last</button>
        </>
      )}
    </div>
  );
}

function Harness(props: { trap?: boolean; empty?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <button type="button">Outside</button>
      {open && <Dialog {...props} onClose={() => setOpen(false)} />}
    </>
  );
}

describe("useDialogFocus", () => {
  it("moves focus to the first focusable thing inside", async () => {
    render(<Harness />);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
  });

  it("focuses the dialog itself when there is nothing inside to focus", async () => {
    render(<Harness empty />);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("wraps Tab from the last element back to the first", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    screen.getByRole("button", { name: "Last" }).focus();
    await userEvent.tab();

    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
  });

  it("wraps Shift+Tab from the first element round to the last", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    await userEvent.tab({ shift: true });

    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
  });

  it("does not let Tab reach anything outside the dialog", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    // Round the whole ring twice; the page behind must never take focus.
    for (let i = 0; i < 6; i += 1) {
      await userEvent.tab();
      expect(screen.getByRole("dialog")).toContainElement(
        document.activeElement as HTMLElement,
      );
    }
  });

  it("closes on Escape", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("gives focus back to whatever opened it", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);

    await userEvent.keyboard("{Escape}");

    expect(opener).toHaveFocus();
  });

  it("lets Tab leave when the trap is off, for menus", async () => {
    render(<Harness trap={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    screen.getByRole("button", { name: "Last" }).focus();
    await userEvent.tab();

    // Out, not round: a menu that swallowed Tab would be the odd one out.
    expect(screen.getByRole("button", { name: "First" })).not.toHaveFocus();
  });

  it("does not steal focus back while the dialog stays open", async () => {
    // The regression this hook was nearly shipped with: `onClose` as an inline
    // arrow made the effect re-run on every parent render, re-focusing the
    // first control while somebody was typing in the third.
    function Rerendering() {
      const [, setTick] = useState(0);
      const panel = useRef<HTMLDivElement>(null);
      useDialogFocus(panel, { onClose: () => undefined });
      return (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Test dialog">
          <button type="button">First</button>
          <input aria-label="Middle" />
          <button type="button" onClick={() => setTick((t) => t + 1)}>
            Re-render
          </button>
        </div>
      );
    }
    render(<Rerendering />);

    const middle = screen.getByLabelText("Middle");
    middle.focus();
    await userEvent.click(screen.getByRole("button", { name: "Re-render" }));
    middle.focus();
    await userEvent.type(middle, "abc");

    expect(middle).toHaveFocus();
    expect(middle).toHaveValue("abc");
  });

  it("does not blow up restoring focus to an opener that unmounted", async () => {
    function Vanishing() {
      const [phase, setPhase] = useState<"button" | "dialog" | "gone">("button");
      const panel = useRef<HTMLDivElement>(null);
      useDialogFocus(panel, { onClose: () => setPhase("gone"), active: phase === "dialog" });
      if (phase === "button") {
        return (
          <button type="button" onClick={() => setPhase("dialog")}>
            Open
          </button>
        );
      }
      if (phase === "gone") return <p>Gone</p>;
      return (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Test dialog">
          <button type="button">Inside</button>
        </div>
      );
    }
    const onError = vi.fn();
    window.addEventListener("error", onError);
    render(<Vanishing />);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.getByText("Gone")).toBeInTheDocument();
    expect(onError).not.toHaveBeenCalled();
    window.removeEventListener("error", onError);
  });
});
