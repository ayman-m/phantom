#!/usr/bin/env node
/**
 * Catalog integrity for lib/journeys.ts: ids are unique, and every id named in
 * `related` or `prerequisites` exists. A dangling id renders a dead link on the
 * journey page. Reads the source text, so it needs no TypeScript support.
 *
 *   node scripts/test-journeys-catalog.mjs   (npm run test:journeys-catalog)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const text = readFileSync(path.join(here, "../lib/journeys.ts"), "utf8");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const ids = [...text.matchAll(/^    id: "([^"]+)",/gm)].map((m) => m[1]);
const known = new Set(ids);

test("the catalog has journeys", () => assert.ok(ids.length > 100, "found " + ids.length));

test("journey ids are unique", () => {
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  assert.deepEqual(dupes, []);
});

test("every related / prerequisites id exists", () => {
  const dangling = new Set();
  for (const m of text.matchAll(/\b(?:related|prerequisites): \[([^\]]*)\]/g)) {
    for (const x of m[1].matchAll(/"([^"]+)"/g)) if (!known.has(x[1])) dangling.add(x[1]);
  }
  assert.deepEqual([...dangling], []);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
