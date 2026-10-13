#!/usr/bin/env node
/**
 * Guard: model providers are reached over HTTPS with explicit credentials,
 * never by spawning a vendor binary. No file under lib/providers/ may mention
 * `child_process` (import, require, dynamic import or otherwise).
 *
 *   node scripts/test-providers-no-child-process.mjs   (npm run test:providers-no-child-process)
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const providersDir = join(root, "lib", "providers");
const SOURCE_EXT = /\.(?:ts|tsx|js|jsx|mjs|cjs)$/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (SOURCE_EXT.test(name)) yield full;
  }
}

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const files = [...walk(providersDir)];
const hits = [];
for (const file of files) {
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (line.includes("child_process")) hits.push(`${relative(root, file)}:${i + 1}`);
  });
}

test("the scan covers the provider modules", () => {
  assert.ok(files.length >= 7, `only ${files.length} files under lib/providers`);
});

test("no file under lib/providers/ mentions child_process", () => {
  assert.deepEqual(hits, []);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
