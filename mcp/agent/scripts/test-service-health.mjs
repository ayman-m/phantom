#!/usr/bin/env node
/**
 * Behaviour test for lib/service-health.ts (how /settings turns the
 * /api/agent/health payload into per-service status). Imports the real
 * TypeScript through Node's built-in type stripping; on an older Node it skips.
 *
 *   node scripts/test-service-health.mjs   (npm run test:service-health)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { serviceHealthRow, languageCounts } = await import("../lib/service-health.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const payload = {
  checkedAt: "2026-10-12T10:00:00Z",
  probes: [
    { id: "phantom-agent", status: "ok", httpStatus: 200, latencyMs: 12 },
    { id: "phantom-mcp", status: "ok", httpStatus: 200, latencyMs: 4 },
    { id: "xlog-api", status: "failed", latencyMs: 5001, error: "timeout" },
    { id: "caldera", status: "skipped" },
  ],
};

test("an ok probe is healthy and carries its latency and check time", () => {
  assert.deepEqual(serviceHealthRow(payload, "phantom-mcp"), {
    status: "healthy", latencyMs: 4, checkedAt: "2026-10-12T10:00:00Z",
  });
});

test("a failed probe is unhealthy", () => {
  assert.equal(serviceHealthRow(payload, "xlog-api").status, "unhealthy");
});

test("a skipped probe (service not configured) is unknown, not healthy", () => {
  const row = serviceHealthRow(payload, "caldera");
  assert.equal(row.status, "unknown");
  assert.equal(row.latencyMs, null);
});

test("a service with no probe id is unknown", () => {
  assert.equal(serviceHealthRow(payload, null).status, "unknown");
});

test("a probe id the route does not report is unknown", () => {
  assert.equal(serviceHealthRow(payload, "nope").status, "unknown");
});

test("an unreachable health route (null payload) leaves every service unknown", () => {
  assert.deepEqual(serviceHealthRow(null, "phantom-mcp"), {
    status: "unknown", latencyMs: null, checkedAt: null,
  });
  assert.equal(serviceHealthRow({}, "phantom-mcp").status, "unknown");
});

test("languages are counted by root, in first-seen order", () => {
  assert.deepEqual(
    languageCounts(["TypeScript / Next.js 15", "Python 3.12 / FastMCP", "Python 3.12 / FastAPI", "C / sqlite3"]),
    [["TypeScript", 1], ["Python", 2], ["C", 1]],
  );
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
