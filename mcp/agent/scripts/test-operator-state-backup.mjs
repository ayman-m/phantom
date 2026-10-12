#!/usr/bin/env node
/**
 * Behaviour test for lib/operator-state-backup.ts: what the backup writes for
 * the operator's workflow state (journeys marked tested, bookmarks) and what
 * restore decides to write back.
 *
 *   node scripts/test-operator-state-backup.mjs   (npm run test:operator-state-backup)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { buildOperatorStateSection, planOperatorStateRestore, OPERATOR_STATE_FILE } =
  await import("../lib/operator-state-backup.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const listed = {
  count: 2,
  entries: [
    { key: "tested_journeys", value: ["a", "b"], updated_at: "2026-10-12T10:00:00.000000Z" },
    { key: "metric_bookmarks", value: [{ name: "q1" }], updated_at: "2026-10-12T11:00:00.000000Z" },
  ],
};

test("the section carries every key with its value and timestamp", () => {
  assert.equal(OPERATOR_STATE_FILE, "operator_state.json");
  const s = buildOperatorStateSection(listed);
  assert.equal(s.count, 2);
  assert.deepEqual(s.entries[0], { key: "tested_journeys", value: ["a", "b"], updated_at: "2026-10-12T10:00:00.000000Z" });
});

test("an empty store or a bad response yields an empty section", () => {
  assert.deepEqual(buildOperatorStateSection({ entries: [], count: 0 }), { count: 0, entries: [] });
  assert.deepEqual(buildOperatorStateSection(null), { count: 0, entries: [] });
  assert.deepEqual(buildOperatorStateSection({ entries: "x" }), { count: 0, entries: [] });
});

test("entries without a key or a value are dropped", () => {
  const s = buildOperatorStateSection({ entries: [{ key: "", value: 1 }, { key: "k" }, { value: 2 }, { key: "ok", value: null }] });
  assert.deepEqual(s.entries.map((e) => e.key), ["ok"]);
});

test("restore writes keys the destination lacks and keeps ones it has", () => {
  const section = buildOperatorStateSection(listed);
  const plan = planOperatorStateRestore(section, ["tested_journeys"], false);
  assert.deepEqual(plan.puts.map((p) => p.key), ["metric_bookmarks"]);
  assert.equal(plan.skipped, 1);
  assert.equal(plan.invalid, 0);
});

test("force overwrites the keys the destination already has", () => {
  const plan = planOperatorStateRestore(buildOperatorStateSection(listed), ["tested_journeys"], true);
  assert.deepEqual(plan.puts.map((p) => p.key).sort(), ["metric_bookmarks", "tested_journeys"]);
  assert.equal(plan.skipped, 0);
  assert.deepEqual(plan.puts.find((p) => p.key === "tested_journeys").value, ["a", "b"]);
});

test("a repeated key is written once, last one wins; unusable entries are counted", () => {
  const plan = planOperatorStateRestore(
    { entries: [{ key: "k", value: 1 }, { key: "k", value: 2 }, { key: "", value: 3 }, "junk"] },
    [],
    false,
  );
  assert.deepEqual(plan.puts, [{ key: "k", value: 2 }]);
  assert.equal(plan.invalid, 2);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
