import { useEffect, useRef, type RefObject } from "react";

/**
 * Focus goes in, stays in, and comes back (spec 071).
 *
 * Twelve components declared `role="dialog"` and not one of them managed focus:
 * you could open the challenge overlay and tab straight through the board
 * underneath it, still focusable, now behind a translucent sheet. Three also
 * declared `aria-modal="true"`, which tells a screen reader everything outside
 * is inert — a promise none of them kept.
 *
 * Four things, because they are the same concern and splitting them is how you
 * end up with ten hand-rolled Escape handlers that each differ slightly:
 *
 * 1. Focus moves in on open.
 * 2. Tab and Shift+Tab cycle inside, never out.
 * 3. Escape closes.
 * 4. Focus returns to whatever opened it — so closing a challenge puts you back
 *    on the row you opened, not at the top of the document.
 *
 * Deliberately not a dependency: it is this long, and a focus-trap package
 * would be more to keep current than the code it replaced.
 */

//: Everything natively focusable, minus anything taken out of the tab order.
//: `:not([disabled])` matters more than it looks — a trap that can land on a
//: disabled submit button is a trap you cannot get out of.
//:
//: Deliberately a selector and not a visibility check. The first version
//: filtered on `offsetParent !== null` to skip CSS-hidden controls, which is
//: untestable under jsdom — it has no layout, so `offsetParent` is always null
//: and the filter silently emptied this list. Nothing in these dialogs hides a
//: focusable control with CSS anyway; they unmount it, the way React does.
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
]
  .map((selector) => `${selector}:not([hidden])`)
  .join(",");

function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
}

export interface DialogFocusOptions {
  /** Called on Escape, and on nothing else — the caller still owns closing. */
  onClose?: () => void;
  /**
   * Off for menus, which are not modal: Tab should walk out of a menu the way
   * it does everywhere else on the web (spec 071 §4).
   */
  trap?: boolean;
  /** Lets a caller keep the hook mounted while the dialog is closed. */
  active?: boolean;
}

export function useDialogFocus(
  ref: RefObject<HTMLElement | null>,
  { onClose, trap = true, active = true }: DialogFocusOptions = {},
): void {
  // Callers pass an inline arrow for `onClose` almost every time. As a
  // dependency that would re-run this effect on every render of the parent —
  // re-capturing the opener and snapping focus back to the first field while
  // somebody was typing in the third. Held in a ref so the effect depends only
  // on whether the dialog is open.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;

    // Captured before we move anything, and restored on the way out. Guests of
    // this hook are usually opened from a button, and that button is where a
    // keyboard user expects to be standing afterwards.
    const returnTo = document.activeElement as HTMLElement | null;

    const first = focusableWithin(root)[0];
    if (first) {
      first.focus();
    } else {
      // Nothing to land on, so the dialog itself takes it. Callers give their
      // container `tabIndex={-1}` for exactly this case.
      root.focus();
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !trap) return;

      const focusable = focusableWithin(root);
      if (focusable.length === 0) {
        // Nothing inside to move between: hold focus rather than letting Tab
        // escape to the page behind.
        event.preventDefault();
        root.focus();
        return;
      }

      const firstItem = focusable[0]!;
      const lastItem = focusable[focusable.length - 1]!;
      const current = document.activeElement;

      if (event.shiftKey && (current === firstItem || current === root)) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && current === lastItem) {
        event.preventDefault();
        firstItem.focus();
      } else if (current instanceof Node && !root.contains(current)) {
        // Focus started outside — something else stole it while we were open.
        event.preventDefault();
        firstItem.focus();
      }
    };

    // Capture, so a dialog inside a dialog takes Escape before its parent does.
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Only if the element is still around: React may have unmounted the
      // opener too, and focusing a detached node silently does nothing.
      if (returnTo?.isConnected) returnTo.focus();
    };
  }, [ref, trap, active]);
}

export default useDialogFocus;
