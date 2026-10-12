#!/usr/bin/env node
/**
 * Behaviour test for lib/permission-policy.ts (a job's tool allow and deny
 * lists). There is no per-job "require approval" list: that key was evaluated
 * but never acted on, so it was removed and a stored policy that still
 * carries it is read with the key ignored.
 *
 *   node scripts/test-permission-policy.mjs   (npm run test:permission-policy)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { evaluatePermissionPolicy, validatePermissionPolicy } = await import("../lib/permission-policy.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("no policy allows everything", () => {
  assert.equal(evaluatePermissionPolicy("jobs_delete", undefined).decision, "allow");
  assert.equal(evaluatePermissionPolicy("jobs_delete", {}).decision, "allow");
});

test("denied wins over allowed", () => {
  const p = { allowed_tools: ["jobs_*"], denied_tools: ["*_delete"] };
  const r = evaluatePermissionPolicy("jobs_delete", p);
  assert.equal(r.decision, "deny");
  assert.equal(r.matchedList, "denied_tools");
  assert.equal(evaluatePermissionPolicy("jobs_list", p).decision, "allow");
});

test("a non-empty allowed list is a whitelist", () => {
  const p = { allowed_tools: ["phantom_*", "xlog.*"] };
  assert.equal(evaluatePermissionPolicy("phantom_create_data_worker", p).decision, "allow");
  assert.equal(evaluatePermissionPolicy("xlog.kill_worker", p).decision, "allow");
  assert.equal(evaluatePermissionPolicy("caldera_get_all_agents", p).decision, "deny");
});

test("a stored require_approval list no longer changes any decision", () => {
  const p = { require_approval: ["jobs_*"] };
  assert.equal(evaluatePermissionPolicy("jobs_create", p).decision, "allow");
});

test("validate keeps the two lists and drops require_approval", () => {
  const v = validatePermissionPolicy({
    allowed_tools: [" a_* ", ""],
    denied_tools: ["b_*"],
    require_approval: ["c_*"],
  });
  assert.deepEqual(v, { allowed_tools: ["a_*"], denied_tools: ["b_*"] });
  assert.equal(validatePermissionPolicy("nope"), null);
  assert.equal(validatePermissionPolicy({ allowed_tools: "x" }), null);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
