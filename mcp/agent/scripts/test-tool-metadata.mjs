#!/usr/bin/env node
/**
 * Behaviour test for lib/tool-metadata.ts: both names of one tool (the legacy
 * flat alias and the namespaced `<connector>.<tool>`) resolve to the same row,
 * including connectors whose functionPrefix differs from their id. That the
 * table only names tools that exist is checked by
 * bundles/spark/mcp/tests/test_shipped_tool_references.py.
 *
 *   node scripts/test-tool-metadata.mjs   (npm run test:tool-metadata)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { resolveToolMetadata, allConcurrencySafe, TOOL_METADATA_TABLE, NAMESPACED_TO_TABLE_KEY } =
  await import("../lib/tool-metadata.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("a read-only XQL tool is concurrency safe under both of its names", () => {
  for (const n of ["xsiam_run_xql_query", "xsiam.run_xql_query"]) {
    const m = resolveToolMetadata(n);
    assert.equal(m.readOnly, true, n);
    assert.equal(m.concurrencySafe, true, n);
  }
});

test("log-generation tools resolve by their namespaced xlog.* name too", () => {
  for (const n of ["phantom_create_data_worker", "xlog.create_data_worker"]) {
    assert.equal(resolveToolMetadata(n).openWorld, true, n);
  }
  assert.equal(resolveToolMetadata("xlog.kill_worker").destructive, true);
  assert.equal(resolveToolMetadata("phantom_kill_worker").destructive, true);
});

test("a CALDERA operation launch is destructive and open-world", () => {
  for (const n of ["caldera_create_operation", "caldera.create_operation"]) {
    const m = resolveToolMetadata(n);
    assert.equal(m.destructive, true, n);
    assert.equal(m.openWorld, true, n);
  }
});

test("every namespaced alias points at a table row", () => {
  for (const [ns, key] of Object.entries(NAMESPACED_TO_TABLE_KEY)) {
    assert.ok(TOOL_METADATA_TABLE[key], `${ns} -> ${key}`);
    assert.equal(resolveToolMetadata(ns), TOOL_METADATA_TABLE[key]);
  }
});

test("tools the old table named but nothing provides now fall through to the safe default", () => {
  for (const n of ["caldera_start_operation", "xlog_create_worker", "api_keys_create"]) {
    const m = resolveToolMetadata(n);
    assert.equal(m.readOnly, false);
    assert.equal(m.concurrencySafe, false);
  }
});

test("a batch is parallel only when every call is concurrency safe", () => {
  assert.equal(allConcurrencySafe(["caldera_get_all_agents", "xsiam_run_xql_query"]), true);
  assert.equal(allConcurrencySafe(["caldera_get_all_agents", "jobs_create"]), false);
  assert.equal(allConcurrencySafe([]), false);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
