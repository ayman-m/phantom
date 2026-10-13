#!/usr/bin/env node
/**
 * Benchmark cost display: a null cost reads "unpriced", never $0.0000, and a
 * change between runs is only computed when both sides have a price. Also pins
 * that the three benchmark pages use these helpers instead of toFixed on a
 * possibly-null cost.
 *
 *   node scripts/test-bench-cost.mjs   (npm run test:bench-cost)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}
const { formatBenchCost, formatBenchCostPair, benchCostDelta } = await import("../lib/bench-cost.ts");

let failed = 0;
const test = (name, fn) => { try { fn(); console.log("ok   " + name); } catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); } };

test("a number shows as dollars with four decimals", () => {
  assert.equal(formatBenchCost(0.0123), "$0.0123");
  assert.equal(formatBenchCost(0), "$0.0000", "a priced zero is a real zero");
});
test("null, undefined and non-finite show as unpriced, never $0.0000", () => {
  for (const v of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) assert.equal(formatBenchCost(v), "unpriced");
});
test("the p50 / p95 pair formats each side on its own", () => {
  assert.equal(formatBenchCostPair(null, null), "unpriced / unpriced");
  assert.equal(formatBenchCostPair(0.1, null), "$0.1000 / unpriced");
});
test("a cost change needs a price on both sides", () => {
  assert.ok(Math.abs(benchCostDelta(0.1, 0.25) - 0.15) < 1e-9);
  assert.equal(benchCostDelta(null, 0.25), null);
  assert.equal(benchCostDelta(0.1, null), null);
  assert.equal(benchCostDelta(undefined, undefined), null);
});

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = (rel) => readFileSync(join(root, "app", "observability", "bench", rel), "utf8");
test("no benchmark page calls toFixed on a cost directly", () => {
  for (const rel of ["page.tsx", "[run_id]/page.tsx", "compare/page.tsx"]) {
    const src = page(rel);
    assert.doesNotMatch(src, /cost_(p50|p95|usd)\.toFixed/, rel);
    assert.match(src, /formatBenchCost|benchCostDelta/, `${rel} uses the shared formatter`);
  }
  assert.match(page("[run_id]/page.tsx"), /cost_usd: number \| null/);
  assert.match(page("compare/page.tsx"), /cost_p50: number \| null/);
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall bench cost tests passed");
