#!/usr/bin/env node
/**
 * Behaviour test for lib/instance-status.ts (how /connectors maps the server's
 * connector `state` onto the instance badge, so the result of the last probe
 * survives a page reload).
 *
 *   node scripts/test-instance-status.mjs   (npm run test:instance-status)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { instanceStatusFromState } = await import("../lib/instance-status.ts");

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

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
