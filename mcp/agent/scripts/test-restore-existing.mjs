#!/usr/bin/env node
/**
 * Behaviour test for lib/restore-existing.ts: what a restore does when it
 * cannot list what the destination already holds. The destination must never
 * be treated as empty then: without Overwrite the section is skipped with a
 * warning; with Overwrite the write goes ahead.
 *
 *   node scripts/test-restore-existing.mjs   (npm run test:restore-existing)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { guardSection, keysFromList, lookupExistingKeys } = await import(
  "../lib/restore-existing.ts"
);

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const instanceKeys = (b) =>
  keysFromList(b, "instances", (i) =>
    typeof i.connector_id === "string" && typeof i.name === "string"
      ? `${i.connector_id}/${i.name}`
      : null,
  );

await test("a good listing yields the destination's keys and the section proceeds", async () => {
  const lookup = await lookupExistingKeys(
    async () => ({ instances: [{ connector_id: "web", name: "a" }, { connector_id: "xlog", name: "b" }] }),
    instanceKeys,
  );
  assert.equal(lookup.ok, true);
  const g = guardSection(lookup, false, "instances", 3);
  assert.equal(g.proceed, true);
  assert.deepEqual([...g.existing].sort(), ["web/a", "xlog/b"]);
  assert.equal(g.warning, undefined);
});

await test("an empty destination is an empty set, not a failure", async () => {
  const lookup = await lookupExistingKeys(async () => ({ instances: [] }), instanceKeys);
  assert.equal(lookup.ok, true);
  assert.equal(guardSection(lookup, false, "instances", 2).proceed, true);
});

await test("a failed listing without Overwrite skips the section with a warning", async () => {
  const lookup = await lookupExistingKeys(async () => { throw new Error("HTTP 503"); }, instanceKeys);
  assert.equal(lookup.ok, false);
  const g = guardSection(lookup, false, "instances", 3);
  assert.equal(g.proceed, false);
  assert.equal(g.existing.size, 0);
  assert.match(g.warning, /instances: skipped 3 entries/);
  assert.match(g.warning, /HTTP 503/);
  assert.match(g.warning, /Overwrite/);
});

await test("a connection error reads the same as an error status", async () => {
  const lookup = await lookupExistingKeys(async () => { throw new TypeError("fetch failed"); }, instanceKeys);
  const g = guardSection(lookup, false, "jobs", 1);
  assert.equal(g.proceed, false);
  assert.match(g.warning, /jobs: skipped 1 entry /);
  assert.match(g.warning, /fetch failed/);
});

await test("a body of the wrong shape is a failure, never an empty destination", async () => {
  for (const body of [{}, { instances: null }, { instances: "x" }, [], null, "oops", 42]) {
    const lookup = await lookupExistingKeys(async () => body, instanceKeys);
    assert.equal(lookup.ok, false, JSON.stringify(body));
    assert.equal(guardSection(lookup, false, "instances", 1).proceed, false);
  }
});

await test("a keysOf that throws is a failure too", async () => {
  const lookup = await lookupExistingKeys(async () => ({}), () => { throw new Error("boom"); });
  assert.equal(lookup.ok, false);
  assert.equal(guardSection(lookup, false, "skills", 2).proceed, false);
});

await test("with Overwrite a failed listing still proceeds, with no known keys", async () => {
  const lookup = await lookupExistingKeys(async () => { throw new Error("HTTP 500"); }, instanceKeys);
  const g = guardSection(lookup, true, "instances", 3);
  assert.equal(g.proceed, true);
  assert.equal(g.existing.size, 0);
  assert.equal(g.warning, undefined);
});

await test("keysFromList reads a bare array and skips unusable items", () => {
  const keys = keysFromList(
    [{ file_path: "a/b.md" }, { nope: 1 }, null, "x", { file_path: "c/d.md" }],
    null,
    (s) => (typeof s.file_path === "string" ? s.file_path : null),
  );
  assert.deepEqual(keys, ["a/b.md", "c/d.md"]);
});

if (failed) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall passed");
