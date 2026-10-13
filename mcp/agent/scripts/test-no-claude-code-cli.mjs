#!/usr/bin/env node
/**
 * Guard: the Claude Code CLI integration is gone and must stay gone. Phantom
 * will only ever talk to Anthropic through the key-based API, never by running
 * the Claude Code binary. This greps every source file under app/, lib/ and
 * components/ for the identifiers of the removed integration and checks that
 * its two files do not exist.
 *
 *   node scripts/test-no-claude-code-cli.mjs   (npm run test:no-claude-code-cli)
 */
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCAN_DIRS = ["app", "lib", "components"];
const SKIP_DIRS = new Set(["node_modules", ".next"]);
const SOURCE_EXT = /\.(?:ts|tsx|js|jsx|mjs|cjs|json|md|css)$/;

const FORBIDDEN = [
  "cli-wrapper",
  "/api/chat/cli",
  "claude-code",
  "claude_code",
  "CLAUDE_CODE_OAUTH_TOKEN",
  "anthropicCliKey",
  "anthropic-cli",
];

const REMOVED_FILES = ["app/api/chat/cli/route.ts", "lib/cli-wrapper.ts"];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) yield* walk(full);
    else if (SOURCE_EXT.test(name)) yield full;
  }
}

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const hits = [];
let scanned = 0;
for (const d of SCAN_DIRS) {
  for (const file of walk(join(root, d))) {
    scanned += 1;
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const term of FORBIDDEN) {
        if (line.includes(term)) hits.push(`${relative(root, file)}:${i + 1}  ${term}`);
      }
    });
  }
}

test("the scan actually covers source files", () => {
  assert.ok(scanned > 100, `only ${scanned} files scanned`);
});

for (const term of FORBIDDEN) {
  test(`no source file under app/ lib/ components/ mentions ${term}`, () => {
    const mine = hits.filter((h) => h.endsWith("  " + term));
    assert.deepEqual(mine, []);
  });
}

for (const f of REMOVED_FILES) {
  test(`${f} stays deleted`, () => {
    assert.equal(existsSync(join(root, f)), false);
  });
}

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
