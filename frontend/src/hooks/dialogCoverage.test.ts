import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Nobody adds the eleventh dialog without focus handling (spec 071 §6).
 *
 * The per-dialog tests prove the behaviour. This proves the *coverage*: a
 * component that announces itself as a dialog and then leaves the keyboard on
 * the page behind it is the exact defect 071 existed to fix, and it is the kind
 * that comes back one component at a time.
 *
 * Source-text assertions are usually a bad smell. This one earns its place
 * because the property is about the whole tree rather than any one render: no
 * amount of testing `ZonePanel` tells you somebody did not add `ZoneDrawer`
 * yesterday.
 */
const SRC = join(__dirname, "..");

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return tsxFiles(full);
    return entry.endsWith(".tsx") && !entry.endsWith(".test.tsx") ? [full] : [];
  });
}

function relative(path: string): string {
  return path.slice(SRC.length + 1).replace(/\\/g, "/");
}

const sources = tsxFiles(SRC).map((path) => ({
  path: relative(path),
  text: readFileSync(path, "utf8"),
}));

describe("dialog focus coverage", () => {
  it("finds the dialogs, so a passing run means something", () => {
    // Guards the guard: if the walk broke, every assertion below would pass
    // over an empty list and prove nothing.
    const dialogs = sources.filter((file) => file.text.includes('role="dialog"'));

    expect(dialogs.length).toBeGreaterThanOrEqual(11);
  });

  it("every role=dialog component uses useDialogFocus", () => {
    const missing = sources
      .filter((file) => file.text.includes('role="dialog"'))
      .filter((file) => !file.text.includes("useDialogFocus"))
      .map((file) => file.path);

    expect(missing).toEqual([]);
  });

  it("every role=menu component uses it too", () => {
    const missing = sources
      .filter((file) => file.text.includes('role="menu"'))
      .filter((file) => !file.text.includes("useDialogFocus"))
      .map((file) => file.path);

    expect(missing).toEqual([]);
  });

  it("nothing claims aria-modal without the hook that makes it true", () => {
    // The claim that everything outside is inert. Three components made it
    // before 071 and none of them kept it.
    const lying = sources
      .filter((file) => file.text.includes('aria-modal="true"'))
      .filter((file) => !file.text.includes("useDialogFocus"))
      .map((file) => file.path);

    expect(lying).toEqual([]);
  });

  it("wires every hook call to a ref that is actually attached", () => {
    // The silent failure this whole file exists to prevent a second time: the
    // hook early-returns when `ref.current` is null, so a call whose ref never
    // reaches an element does *nothing at all* — no trap, no restore, and no
    // error to notice. Nothing at runtime distinguishes that from working.
    const unattached = sources
      .filter((file) => file.text.includes("useDialogFocus("))
      .flatMap((file) => {
        const refs = [...file.text.matchAll(/useDialogFocus\(\s*(\w+)/g)].map((m) => m[1]);
        return refs
          .filter((name) => !file.text.includes(`ref={${name}}`))
          .map((name) => `${file.path}: ${name}`);
      });

    expect(unattached).toEqual([]);
  });

  it("no dialog keeps a hand-rolled Escape handler", () => {
    // Nine of these existed and several differed in whether they re-bound on
    // every render. The hook owns Escape now; a new one beside it would drift.
    const handRolled = sources
      .filter((file) => file.text.includes("useDialogFocus"))
      .filter((file) => /=== "Escape"/.test(file.text))
      .map((file) => file.path);

    expect(handRolled).toEqual([]);
  });
});
