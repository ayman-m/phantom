#!/usr/bin/env node
/**
 * Behaviour test for lib/instance-status.ts: how /connectors maps the server's
 * connector `state` onto the instance badge (so the result of the last probe
 * survives a page reload), what the "tools available" note says, and what a
 * Test Connection press means.
 *
 *   node scripts/test-instance-status.mjs   (npm run test:instance-status)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { instanceStatusFromState, toolNote, testOutcome, saveOutcome, NO_BUILT_IN_TEST } = await import("../lib/instance-status.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("a connected state stays connected after a reload", () => {
  assert.equal(instanceStatusFromState("connected"), "connected");
});

test("failed and needs-auth both show as an error", () => {
  assert.equal(instanceStatusFromState("failed"), "error");
  assert.equal(instanceStatusFromState("needs-auth"), "error");
});

test("pending, disabled, missing and unknown values show as not tested", () => {
  for (const v of ["pending", "disabled", "", undefined, null, 7, "weird"]) {
    assert.equal(instanceStatusFromState(v), "not_tested");
  }
});

// ── the "tools available" note ──────────────────────────────────────────────
// The agent can call an enabled instance's tools whatever its connector state is
// (connector_loader.py registers tools on install + instance, never on state).

test("every state of an enabled instance has its tools available", () => {
  for (const state of ["connected", "pending", "failed", "needs-auth", "disabled", undefined, "weird"]) {
    assert.equal(toolNote({ enabled: true, state }).available, true, String(state));
  }
});

test("a never-tested instance says 'not tested yet', neutral, and never 'paused'", () => {
  for (const state of ["pending", undefined, null, "weird"]) {
    const n = toolNote({ enabled: true, state });
    assert.equal(n.label, "Tools available · not tested yet");
    assert.equal(n.tone, "neutral");
    assert.doesNotMatch(n.label + n.title, /paused|not connected/i);
  }
});

test("a connected instance is plainly available", () => {
  const n = toolNote({ enabled: true, state: "connected" });
  assert.equal(n.label, "Tools available to agent");
  assert.equal(n.tone, "ok");
});

test("failed and needs-auth warn but still say the tools are available", () => {
  const failing = toolNote({ enabled: true, state: "failed", lastError: "cannot connect to x:9222" });
  assert.equal(failing.label, "Tools available · connection failing");
  assert.equal(failing.tone, "warn");
  assert.match(failing.title, /cannot connect to x:9222/);
  assert.match(failing.title, /can call this connector's tools/);
  const auth = toolNote({ enabled: true, state: "needs-auth" });
  assert.equal(auth.label, "Tools available · credentials rejected");
  assert.equal(auth.tone, "warn");
});

test("only a disabled instance is paused, whatever its state", () => {
  for (const state of ["connected", "pending", "failed", "needs-auth"]) {
    const n = toolNote({ enabled: false, state });
    assert.equal(n.label, "Tools paused (disabled)");
    assert.equal(n.available, false);
    assert.equal(n.tone, "paused");
  }
});

// ── what a Test Connection press means ──────────────────────────────────────

test("a passing probe is connected and shows what it proved", () => {
  const o = testOutcome({ probe_implemented: true, ok: true, message: "the collector is reachable; the key is NOT verified" });
  assert.deepEqual(o, { kind: "passed", status: "connected", message: "the collector is reachable; the key is NOT verified" });
  assert.equal(testOutcome({ probe_implemented: true, ok: true }).message, "Connection OK.");
});

test("a failing probe is an error and carries the reason", () => {
  const o = testOutcome({ probe_implemented: true, ok: false, error: "HTTP 401 from XSIAM" });
  assert.equal(o.kind, "failed");
  assert.equal(o.status, "error");
  assert.equal(o.message, "Test failed: HTTP 401 from XSIAM");
  assert.equal(testOutcome({ probe_implemented: true, ok: false }).message, "Test failed: unknown error");
});

test("a connector with no probe says so plainly and keeps its badge", () => {
  const none = testOutcome({ probe_implemented: false, connector_state: { state: "pending" } });
  assert.equal(none.kind, "no_test");
  assert.equal(none.status, "not_tested");
  assert.equal(none.message, NO_BUILT_IN_TEST);
  assert.equal(NO_BUILT_IN_TEST, "This connector has no built-in test.");
  const kept = testOutcome({ probe_implemented: false, message: "x", connector_state: { state: "connected" } });
  assert.equal(kept.status, "connected");
  assert.equal(kept.message, "x");
});

test("the connectors page no longer claims tools are paused for a connector that is not connected", () => {
  const page = readFileSync(new URL("../app/connectors/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /Tools paused \(not connected\)/);
  assert.doesNotMatch(page, /Probe not wired for this connector/);
  assert.match(page, /toolNote\(/);
});

test("a save says whether the connector restarted to load the new settings", () => {
  assert.deepEqual(saveOutcome(undefined, "web"), { type: "success", message: "Instance updated successfully." });
  assert.deepEqual(saveOutcome(null, "web").type, "success");
  const done = saveOutcome({ ok: true, status: "restarted" }, "http-sender");
  assert.equal(done.type, "success");
  assert.match(done.message, /restarted and is using the new settings/);
  const busy = saveOutcome({ ok: true, status: "in_progress" }, "http-sender");
  assert.equal(busy.type, "info");
  assert.match(busy.message, /is restarting to load the new settings/);
  const bad = saveOutcome({ ok: false, status: "failed", error: "phantom-updater could not be reached" }, "http-sender");
  assert.equal(bad.type, "error");
  assert.match(bad.message, /^Saved, but the connector could not be restarted \(phantom-updater could not be reached\)/);
  assert.match(bad.message, /may be stopped/);
  assert.match(bad.message, /settings are stored/);
  assert.match(bad.message, /off and on again/);
  assert.doesNotMatch(bad.message, /docker restart|old settings/);
  assert.doesNotMatch(saveOutcome({ ok: false, status: "failed" }, "web").message, /\(\)/);
});

test("the Edit dialog and the row toggle both show the restart outcome", () => {
  const page = readFileSync(new URL("../app/connectors/page.tsx", import.meta.url), "utf8");
  assert.ok((page.match(/saveOutcome\(/g) ?? []).length >= 2, "Save and the enable toggle both call saveOutcome");
  assert.match(page, /notify\(/);
  assert.doesNotMatch(page, /window\.(alert|confirm|prompt)\(/);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
