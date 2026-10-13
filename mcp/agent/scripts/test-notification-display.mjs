#!/usr/bin/env node
/**
 * Behaviour test for lib/notification-display.ts (how /notifications renders a
 * store row). Imports the real TypeScript through Node's built-in type
 * stripping; on an older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-notification-display.mjs   (npm run test:notification-display)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { describeNotification, humanizeTopic, sinceForRange, appendPage, DATE_RANGES } = await import("../lib/notification-display.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("a completed job row shows the job name, the summary and links to the job", () => {
  const d = describeNotification({
    id: "n1",
    topic: "job-run-completed",
    payload: { job_name: "journey-run-now", summary: "Job journey-run-now succeeded in 12150ms" },
    created_at: "2026-10-12T10:00:00Z",
  });
  assert.equal(d.title, "Job journey-run-now succeeded");
  assert.equal(d.description, "Job journey-run-now succeeded in 12150ms");
  assert.equal(d.href, "/jobs/journey-run-now");
  assert.equal(d.tone, "success");
});

test("a failed job row says failed and falls back to the error text", () => {
  const d = describeNotification({
    id: "n2",
    topic: "job-run-failed",
    payload: { job_name: "nightly sweep", error: "HTTP 401" },
  });
  assert.equal(d.title, "Job nightly sweep failed");
  assert.equal(d.description, "HTTP 401");
  assert.equal(d.href, "/jobs/nightly%20sweep");
  assert.equal(d.tone, "failure");
});

test("a job row without a job name has no link and a plain title", () => {
  const d = describeNotification({ id: "n3", topic: "job-run-completed", payload: {} });
  assert.equal(d.title, "Job run completed");
  assert.equal(d.href, undefined);
});

test("another topic uses payload.title and payload.body", () => {
  const d = describeNotification({
    id: "n4",
    topic: "coverage-cycle",
    payload: { title: "Coverage cycle: 2 drift", body: "details" },
  });
  assert.equal(d.title, "Coverage cycle: 2 drift");
  assert.equal(d.description, "details");
  assert.equal(d.tone, "neutral");
});

test("the built-in hook warnings show the payload title, the body, and the warning tone", () => {
  const cost = describeNotification({
    id: "w1",
    topic: "cost-warning",
    payload: { title: "Daily chat cost crossed threshold \u2014 $12.34 so far", body: "details" },
  });
  assert.equal(cost.title, "Daily chat cost crossed threshold \u2014 $12.34 so far");
  assert.equal(cost.description, "details");
  assert.equal(cost.tone, "warning");
  const ctx = describeNotification({
    id: "w2",
    topic: "context-warning",
    payload: { title: "Chat context filling up \u2014 compaction imminent", body: "Session s1 ..." },
  });
  assert.equal(ctx.title, "Chat context filling up \u2014 compaction imminent");
  assert.equal(ctx.tone, "warning");
});

test("a hook warning without a payload title falls back to the humanized topic", () => {
  assert.equal(describeNotification({ id: "w3", topic: "cost-warning", payload: {} }).title, "Cost warning");
  assert.equal(describeNotification({ id: "w4", topic: "context-warning" }).title, "Context warning");
});

test("an unknown topic gets a humanized title and the payload summary", () => {
  const d = describeNotification({ id: "n5", topic: "simulation-complete", payload: { summary: "Done" } });
  assert.equal(d.title, "Simulation complete");
  assert.equal(d.description, "Done");
});

test("a non-object payload does not throw", () => {
  const d = describeNotification({ id: "n6", topic: "x", payload: "oops" });
  assert.equal(d.title, "X");
  assert.equal(d.description, "");
});

test("read state follows read_at from the store row", () => {
  assert.equal(describeNotification({ id: "a", read_at: "2026-10-12T10:00:00Z" }).read, true);
  assert.equal(describeNotification({ id: "b", read_at: null }).read, false);
});

test("humanizeTopic handles separators", () => {
  assert.equal(humanizeTopic("approval:requested"), "Approval requested");
});

test("the date ranges offer All time first and map to since timestamps in the store's format", () => {
  assert.equal(DATE_RANGES[0].value, "all");
  const now = new Date(2026, 9, 12, 15, 30, 0); // local 2026-10-12 15:30
  assert.equal(sinceForRange("all", now), undefined);
  const today = sinceForRange("today", now);
  assert.equal(new Date(today.replace("000Z", "Z")).getTime(), new Date(2026, 9, 12).getTime());
  assert.match(today, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/);
  const week = sinceForRange("7d", now);
  assert.equal(new Date(week.replace("000Z", "Z")).getTime(), now.getTime() - 7 * 86400000);
  const month = sinceForRange("30d", now);
  assert.equal(new Date(month.replace("000Z", "Z")).getTime(), now.getTime() - 30 * 86400000);
});

test("appending a page skips rows already shown and keeps order", () => {
  const merged = appendPage([{ id: "a" }, { id: "b" }], [{ id: "b" }, { id: "c" }]);
  assert.deepEqual(merged.map((r) => r.id), ["a", "b", "c"]);
  assert.deepEqual(appendPage([], [{ id: "x" }]).map((r) => r.id), ["x"]);
});

if (failed) { console.log(failed + " test(s) failed"); process.exit(1); }
console.log("all passed");
