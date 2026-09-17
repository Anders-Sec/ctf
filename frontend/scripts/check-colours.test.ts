import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

/**
 * The linter is the thing that keeps spec 048's migration done, so it gets its
 * own test — a rule that silently stops matching is worse than no rule, because
 * it reads as enforcement.
 *
 * Each case runs the real script against a scratch tree rather than importing
 * its internals: what matters is the exit code a CI run would see.
 */

const SCRIPT = join(process.cwd(), "scripts", "check-colours.mjs");

let scratch: string | null = null;

function project(files: Record<string, string>): string {
  scratch = mkdtempSync(join(tmpdir(), "colours-"));
  mkdirSync(join(scratch, "scripts"), { recursive: true });
  cpSync(SCRIPT, join(scratch, "scripts", "check-colours.mjs"));
  for (const [path, contents] of Object.entries(files)) {
    const full = join(scratch, path);
    mkdirSync(join(full, ".."), { recursive: true });
    writeFileSync(full, contents, "utf8");
  }
  return scratch;
}

/** Exit code plus whatever the script printed, merged. */
function run(root: string): { code: number; output: string } {
  try {
    const output = execFileSync(process.execPath, [join(root, "scripts", "check-colours.mjs")], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { code: 0, output };
  } catch (error) {
    const failure = error as { status: number; stdout: string; stderr: string };
    return { code: failure.status, output: `${failure.stdout}${failure.stderr}` };
  }
}

afterEach(() => {
  if (scratch) rmSync(scratch, { recursive: true, force: true });
  scratch = null;
});

describe("the colour linter", () => {
  it("passes a file that only uses role tokens", () => {
    const root = project({
      "src/Ok.tsx": `export const a = <p className="bg-surface-raised text-content-muted" />;`,
    });
    expect(run(root).code).toBe(0);
  });

  it("fails on bg-white — the class the whole migration was about", () => {
    const root = project({
      "src/Bad.tsx": `export const a = <p className="bg-white/60" />;`,
    });
    const { code, output } = run(root);
    expect(code).toBe(1);
    expect(output).toContain("bg-white/60");
  });

  it("fails on a stock-palette class", () => {
    const root = project({
      "src/Bad.tsx": `export const a = <p className="text-red-600" />;`,
    });
    expect(run(root).code).toBe(1);
  });

  it("fails on a hex literal", () => {
    const root = project({ "src/Bad.tsx": `const glow = "#ffca7a";` });
    const { code, output } = run(root);
    expect(code).toBe(1);
    expect(output).toContain("#ffca7a");
  });

  it("fails on a literal rgba()", () => {
    const root = project({ "src/Bad.css": `.x { color: rgba(255, 157, 61, 0.9); }` });
    expect(run(root).code).toBe(1);
  });

  it("allows rgb(var(--token) / alpha)", () => {
    const root = project({
      "src/Ok.css": `.x { color: rgb(var(--accent) / 0.9); }`,
    });
    expect(run(root).code).toBe(0);
  });

  it("allows alpha stops inside a mask gradient", () => {
    // In a mask, black means opaque and the hue is never painted — spec 023's
    // feathered map edge is a mask, not a colour.
    const root = project({
      "src/Ok.css": `.x { mask-image: radial-gradient(#000 62%, rgba(0, 0, 0, 0.85) 82%, transparent); }`,
    });
    expect(run(root).code).toBe(0);
  });

  it("does not police test files, which may assert on a class name", () => {
    const root = project({
      "src/Thing.test.tsx": `expect(el).toHaveClass("bg-white/60");`,
    });
    expect(run(root).code).toBe(0);
  });

  it("exempts the token definitions and the theme-invariant map", () => {
    const root = project({
      "src/theme/themes.css": `:root { --accent: 176 92 32; } .x { color: #ffca7a; }`,
      "src/components/DungeonMap.tsx": `const PALETTE = { torch: "#ff9d3d" };`,
    });
    expect(run(root).code).toBe(0);
  });
});
