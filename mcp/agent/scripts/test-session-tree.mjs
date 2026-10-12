#!/usr/bin/env node
/**
 * Behaviour test for lib/session-tree.ts, the ordering behind the chat
 * sidebar: sessions bucketed by date, a forked session listed directly under
 * its parent and indented one level per generation.
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-session-tree.mjs   (npm run test:session-tree)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { groupSessionTree, dateGroupOf } = await import("../lib/session-tree.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const NOW = new Date(2026, 9, 12, 12, 0, 0, 0); // local time, like the browser
const at = (daysAgo, hour = 9) => new Date(2026, 9, 12 - daysAgo, hour, 0, 0).toISOString();
const s = (id, timestamp, parentId = null) => ({ id, timestamp, parentId });
/** Flatten to "id:depth" strings for easy comparison. */
const flat = (buckets) => buckets.flatMap((b) => b.rows.map((r) => `${r.session.id}:${r.depth}`));

test("a fork is listed directly under its parent, indented one level", () => {
  const out = groupSessionTree(
    [s("other", at(0, 10)), s("root", at(0, 8)), s("fork", at(0, 9), "root")],
    NOW,
  );
  assert.deepEqual(flat(out), ["other:0", "root:0", "fork:1"]);
});

test("grandchildren sit under their own parent, not after the sibling forks", () => {
  // The old depth-ascending sort produced root, A, B, A1; depth-first is
  // root, B, A, A1 (newest sibling first).
  const out = groupSessionTree(
    [
      s("root", at(0, 1)),
      s("A", at(0, 2), "root"),
      s("B", at(0, 3), "root"),
      s("A1", at(0, 4), "A"),
    ],
    NOW,
  );
  assert.deepEqual(flat(out), ["root:0", "B:1", "A:1", "A1:2"]);
});

test("a fork made on a later day stays in its root's date bucket", () => {
  const out = groupSessionTree(
    [s("root", at(3)), s("fork", at(0), "root"), s("today", at(0, 11))],
    NOW,
  );
  assert.deepEqual(out.map((b) => b.group), ["Today", "Previous 7 Days"]);
  assert.deepEqual(flat(out), ["today:0", "root:0", "fork:1"]);
});

test("a fork whose parent is not in the list is a root at depth 0", () => {
  const out = groupSessionTree([s("orphan", at(0), "deleted-parent")], NOW);
  assert.deepEqual(flat(out), ["orphan:0"]);
});

test("a parent cycle does not loop and still lists every session once", () => {
  const out = groupSessionTree([s("a", at(0, 1), "b"), s("b", at(0, 2), "a")], NOW);
  const ids = flat(out).map((x) => x.split(":")[0]).sort();
  assert.deepEqual(ids, ["a", "b"]);
});

test("a session that is its own parent is a root", () => {
  assert.deepEqual(flat(groupSessionTree([s("x", at(0), "x")], NOW)), ["x:0"]);
});

test("empty date buckets are omitted and an empty list yields none", () => {
  assert.deepEqual(groupSessionTree([], NOW), []);
  const out = groupSessionTree([s("old", at(30))], NOW);
  assert.deepEqual(out.map((b) => b.group), ["Older"]);
});

test("date groups: today, yesterday, last week, older", () => {
  assert.equal(dateGroupOf(at(0), NOW), "Today");
  assert.equal(dateGroupOf(at(1), NOW), "Yesterday");
  assert.equal(dateGroupOf(at(5), NOW), "Previous 7 Days");
  assert.equal(dateGroupOf(at(20), NOW), "Older");
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall session-tree tests passed");
