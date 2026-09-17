#!/usr/bin/env node
/**
 * Fail the build on a raw colour (spec 048 §7.5).
 *
 * This is the step that makes the migration stay done. The token layer in
 * `tailwind.config.js` was designed for theming from the start, with a comment
 * saying so — and by Phase 3 there were ~100 `bg-white/xx` uses across 41
 * files, because nothing stopped them. A convention nobody can enforce is a
 * convention that decays.
 *
 * Run: npm run lint:colours
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");

/**
 * Files allowed to name colours directly, each for a stated reason. Adding an
 * entry here is a decision; it should come with the reason, in this table.
 */
const ALLOWED = new Map([
  [
    "src/theme/themes.css",
    "The token definitions themselves. Somewhere has to hold the values.",
  ],
  [
    "src/components/DungeonMap.tsx",
    "Theme-invariant art (spec 048 §9.3). The map is raster tiles with baked-in " +
      "lighting and its own dark atmosphere from spec 023; a themed glow would be " +
      "the one lit thing disagreeing with everything around it.",
  ],
]);

const RULES = [
  {
    // Tailwind's stock palette and the two absolutes. `stone` is excluded from
    // the scale check because the config defines it as a single token — and
    // `bg-stone-500` therefore emits NO CSS, which is how the Wordle "absent"
    // tile spent Phase 2 with no background at all.
    pattern:
      /\b(?:text|bg|border|ring|fill|stroke|from|via|to|placeholder|decoration|divide|outline|shadow|accent|caret)-(?:white|black|slate|gray|grey|zinc|neutral|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g,
    message: "Tailwind's stock palette is not themeable. Use a role token.",
  },
  {
    pattern: /#[0-9a-fA-F]{3,8}\b/g,
    message: "Hex literal. Use a role token.",
    // `#000` inside a mask-image is an alpha stop, not a colour — in a mask,
    // black means opaque and the hue is never painted.
    skip: (line) => /mask-image|mask:/.test(line) || /^\s*(?:#[0-9a-fA-F]{3,8}|rgba?\()/.test(line) && /mask/.test(line),
  },
  {
    pattern: /\brgba?\(\s*\d/g,
    message: "Literal rgb()/rgba(). Use rgb(var(--token) / alpha).",
  },
];

/** Gradient stops in a mask are alpha, not colour. */
const MASK_BLOCK = /mask-image:[^;]*;/gs;

function walk(dir) {
  const found = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      found.push(...walk(path));
    } else if ([".ts", ".tsx", ".css"].includes(extname(path))) {
      found.push(path);
    }
  }
  return found;
}

const failures = [];

for (const path of walk(SRC)) {
  const rel = relative(ROOT, path).replace(/\\/g, "/");
  if (ALLOWED.has(rel)) continue;

  // Tests may assert on a class name; they render nothing.
  if (/\.test\.tsx?$/.test(rel)) continue;

  let source = readFileSync(path, "utf8");
  // Blank out mask gradients before scanning, so their alpha stops do not read
  // as colours.
  source = source.replace(MASK_BLOCK, (match) => match.replace(/\S/g, " "));

  source.split("\n").forEach((line, index) => {
    for (const rule of RULES) {
      if (rule.skip?.(line)) continue;
      for (const match of line.matchAll(rule.pattern)) {
        failures.push({
          file: rel,
          line: index + 1,
          found: match[0],
          message: rule.message,
        });
      }
    }
  });
}

if (failures.length === 0) {
  console.log("colours: clean — no raw colour outside the token definitions.");
  process.exit(0);
}

console.error(`colours: ${failures.length} raw colour${failures.length === 1 ? "" : "s"} found.\n`);
for (const failure of failures) {
  console.error(`  ${failure.file}:${failure.line}  ${failure.found}`);
  console.error(`    ${failure.message}\n`);
}
console.error(
  "Role tokens are defined in src/theme/themes.css and mapped in tailwind.config.js.",
);
process.exit(1);
