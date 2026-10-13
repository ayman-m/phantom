#!/usr/bin/env node
/**
 * The personality defaults have one canonical home: DEFAULT_PERSONALITY in
 * the MCP's personality_store.py (it seeds a fresh install and answers
 * GET /api/v1/personality/defaults, which the personality page reads for
 * first load and for Reset Defaults). The one other copy is the chat
 * route's fallback, DEFAULT_ACTION_POLICY in lib/system-prompt.ts; this test
 * fails if the two disagree. It also pins that the personality page carries
 * no defaults of its own and no control for a setting nothing reads.
 *
 *   node scripts/test-personality-defaults.mjs   (npm run test:personality-defaults)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.join(here, rel), "utf8");
const store = read("../../../bundles/spark/mcp/src/usecase/personality_store.py");
const page = read("../app/settings/personality/page.tsx");
const { DEFAULT_ACTION_POLICY } = await import("../lib/system-prompt.ts");
const { resolveConfig } = await import("../lib/personality-config.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

/** The quoted strings of `"<key>": [ ... ]` inside the Python default. */
function pyList(key) {
  const m = store.match(new RegExp(`"${key}": \\[([^\\]]*)\\]`));
  assert.ok(m, `${key} list not found in personality_store.py`);
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}
function pyScalar(key) {
  const m = store.match(new RegExp(`"${key}": ("[^"]*"|True|False)`));
  assert.ok(m, `${key} not found in personality_store.py`);
  return m[1] === "True" ? true : m[1] === "False" ? false : m[1].slice(1, -1);
}

test("the chat route fallback lists the same local categories as the store", () => {
  assert.deepEqual(DEFAULT_ACTION_POLICY.localCategories, pyList("localCategories"));
});

test("the chat route fallback lists the same external categories as the store", () => {
  assert.deepEqual(DEFAULT_ACTION_POLICY.externalCategories, pyList("externalCategories"));
});

test("both defaults classify http-sender and wec-sender as external", () => {
  for (const c of ["http-sender", "wec-sender"]) {
    assert.ok(DEFAULT_ACTION_POLICY.externalCategories.includes(c), `${c} missing from the TS default`);
    assert.ok(pyList("externalCategories").includes(c), `${c} missing from the store default`);
  }
});

test("the chat route fallback uses the same cadences and ask-when-unsure as the store", () => {
  assert.equal(DEFAULT_ACTION_POLICY.askWhenUnsure, pyScalar("askWhenUnsure"));
  assert.equal(DEFAULT_ACTION_POLICY.confirmLocalActions, pyScalar("confirmLocalActions"));
  assert.equal(DEFAULT_ACTION_POLICY.confirmExternalActions, pyScalar("confirmExternalActions"));
});

test("the personality page holds no copy of the defaults", () => {
  assert.doesNotMatch(page, /DEFAULT_CONFIG/);
  assert.doesNotMatch(page, /# Phantom Personality/);
  assert.doesNotMatch(page, /externalCategories:\s*\[/);
  assert.match(page, /\/api\/agent\/personality\/defaults/);
});

test("the personality page has no control for a setting nothing reads", () => {
  for (const knob of ["vertexCacheEnabled", "autoCompactMinDropped", "memoryMmrLambda", "memoryTemporalDecayLambda"]) {
    assert.ok(!page.includes(knob), `${knob} is back on the personality page`);
  }
  assert.doesNotMatch(page, /title="Tuning"/);
});

// ── resolveConfig: how the page lays a stored blob over the MCP defaults ──

const defaults = {
  personalityMd: "# Default\n",
  actionPolicy: { ...DEFAULT_ACTION_POLICY },
};

test("a stored value wins; a key the blob lacks takes the default", () => {
  const got = resolveConfig(defaults, { personalityMd: "# Mine\n" });
  assert.equal(got.personalityMd, "# Mine\n");
  assert.deepEqual(got.actionPolicy, defaults.actionPolicy);
});

test("a partial stored actionPolicy is completed field by field", () => {
  const got = resolveConfig(defaults, { actionPolicy: { askWhenUnsure: false } });
  assert.equal(got.actionPolicy.askWhenUnsure, false);
  assert.deepEqual(got.actionPolicy.externalCategories, defaults.actionPolicy.externalCategories);
  assert.equal(got.actionPolicy.confirmExternalActions, "off");
});

test("a stored externalCategories list is kept exactly as saved", () => {
  const got = resolveConfig(defaults, { actionPolicy: { externalCategories: ["xlog"] } });
  assert.deepEqual(got.actionPolicy.externalCategories, ["xlog"]);
});

test("keys an older release stored, including the retired Tuning knobs, are dropped", () => {
  const got = resolveConfig(defaults, {
    personalityMd: "x",
    permissionLevel: "high",
    vertexCacheEnabled: true,
    autoCompactMinDropped: 2,
    memoryMmrLambda: 0.5,
    memoryTemporalDecayLambda: 0.02,
  });
  assert.deepEqual(Object.keys(got).sort(), ["actionPolicy", "personalityMd"]);
});

test("an empty stored blob resolves to the defaults (Reset Defaults)", () => {
  assert.deepEqual(resolveConfig(defaults, {}), defaults);
});

test("malformed defaults resolve to null rather than a half-built document", () => {
  assert.equal(resolveConfig({}, {}), null);
  assert.equal(resolveConfig({ personalityMd: "x" }, {}), null);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
