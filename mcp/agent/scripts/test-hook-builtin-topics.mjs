#!/usr/bin/env node
/**
 * The built-in hooks publish to fixed notification topics. The MCP's
 * notification store rejects a topic that bundles/spark/manifest.yaml does
 * not declare, so the constants in lib/hook-builtins/notification-topics.ts
 * and the manifest must agree. (The Python side asserts the same from the
 * other direction: bundles/spark/mcp/tests/test_hook_builtin_topics.py.)
 *
 * Also guards the retired `notify_category` setting: the built-in sources must
 * not read it, and the dynamic config form must not offer it.
 *
 *   node scripts/test-hook-builtin-topics.mjs   (npm run test:hook-builtin-topics)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const here = dirname(fileURLToPath(import.meta.url));
const { BUILTIN_HOOK_TOPICS, COST_WARNING_TOPIC, CONTEXT_WARNING_TOPIC } = await import(
  "../lib/hook-builtins/notification-topics.ts"
);

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

function manifestTopics() {
  const text = readFileSync(resolve(here, "../../../bundles/spark/manifest.yaml"), "utf8");
  const names = [];
  for (const m of text.matchAll(/^\s*-\s*\{\s*name:\s*"([^"]+)",\s*severity:\s*"([^"]+)"/gm)) {
    names.push({ name: m[1], severity: m[2] });
  }
  return names;
}

test("the two topics are the ones the journey and docs name", () => {
  assert.equal(COST_WARNING_TOPIC, "cost-warning");
  assert.equal(CONTEXT_WARNING_TOPIC, "context-warning");
  assert.deepEqual([...BUILTIN_HOOK_TOPICS].sort(), ["context-warning", "cost-warning"]);
});

test("every topic a built-in hook publishes is declared in the manifest", () => {
  const declared = manifestTopics();
  assert.ok(declared.length > 5, "parsed the manifest topic list");
  for (const topic of BUILTIN_HOOK_TOPICS) {
    const hit = declared.find((t) => t.name === topic);
    assert.ok(hit, `${topic} is not declared in bundles/spark/manifest.yaml notifications.topics`);
    assert.equal(hit.severity, "warning");
  }
});

test("each built-in publishes through its constant, not a configurable topic", () => {
  for (const [file, constant] of [
    ["cost-warn-over-budget.ts", "COST_WARNING_TOPIC"],
    ["pre-compact-context-warning.ts", "CONTEXT_WARNING_TOPIC"],
  ]) {
    const src = readFileSync(resolve(here, "../lib/hook-builtins", file), "utf8");
    assert.ok(src.includes(constant), `${file} does not use ${constant}`);
    assert.ok(!/key:\s*"notify_category"/.test(src), `${file} still offers a notify_category field`);
    assert.ok(!/config\.notify_category|cfg\.notify_category/.test(src), `${file} still reads notify_category`);
  }
});

if (failed) { console.log(failed + " test(s) failed"); process.exit(1); }
console.log("all passed");
