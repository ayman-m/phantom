#!/usr/bin/env node
/**
 * Behaviour test for the "Model in use" block of lib/system-prompt.ts.
 *
 * A per-session `/model <name>` preference is not a global setting. The prompt
 * must state the model serving the turn as read-only context and forbid
 * answering model questions (or recording the session model) through the
 * settings tools. The tool layer enforces the same rule (settings_update and
 * settings_reset refuse model-selection keys); this guards the prompt side.
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-system-prompt-model.mjs   (npm run test:system-prompt-model)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { renderModelContextBlock, buildSystemPromptText } = await import("../lib/system-prompt.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const policy = { localCategories: [], externalCategories: [], confirmLocalActions: "never" };

test("the block states the model serving the turn", () => {
  const block = renderModelContextBlock("gemini-2.5-pro");
  assert.match(block, /served by the model `gemini-2\.5-pro`/);
});

test("model questions are answered from context, not via settings tools", () => {
  const block = renderModelContextBlock("gemini-2.5-pro");
  assert.match(block, /Do NOT call `settings_get`,\s+`settings_update`/);
});

test("a session preference is never written into a global setting", () => {
  const block = renderModelContextBlock("gemini-2.5-pro");
  assert.match(block, /per-session `\/model` preference is NOT a global setting/);
  assert.match(block, /never\s+write it into `geminiModel`/);
});

test("the rule is still emitted when the model is unknown", () => {
  for (const unknown of [undefined, null, "", "   "]) {
    const block = renderModelContextBlock(unknown);
    assert.doesNotMatch(block, /served by the model/);
    assert.match(block, /Do NOT call `settings_get`/);
  }
});

test("the full prompt carries the block, with the turn's model", () => {
  const text = buildSystemPromptText(policy, null, [], "manual", undefined, "gemini-2.5-pro");
  assert.match(text, /## CRITICAL - Model in use/);
  assert.match(text, /served by the model `gemini-2\.5-pro`/);
});

test("the full prompt without a model still carries the rule", () => {
  const text = buildSystemPromptText(policy);
  assert.match(text, /## CRITICAL - Model in use/);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
