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
  const block = renderModelContextBlock("vertex/gemini-3.1-pro-preview");
  assert.match(block, /served by the model `vertex\/gemini-3\.1-pro-preview`/);
});

test("model questions are answered from context, not via settings tools", () => {
  const block = renderModelContextBlock("vertex/gemini-3.1-pro-preview");
  assert.match(block, /Do NOT call `settings_get`,\s+`settings_update`/);
});

test("a session preference is never written into a global setting", () => {
  const block = renderModelContextBlock("vertex/gemini-3.1-pro-preview");
  assert.match(block, /per-session `\/model` preference is NOT a global setting/);
  assert.match(block, /never\s+write it into `defaultModel`/);
});

test("the wording is neutral about the provider and takes a canonical ref from any of them", () => {
  for (const ref of ["vertex/gemini-3.1-pro-preview", "anthropic/claude-opus-5-5", "openai/gpt-6-sol"]) {
    const block = renderModelContextBlock(ref);
    assert.match(block, new RegExp("served by the model `" + ref.replace(/[./-]/g, "\\$&") + "`"));
    // Nothing in the block assumes the model is a Gemini.
    assert.doesNotMatch(block.split(ref).join(""), /Gemini|geminiModel/i);
    assert.match(block, /"which model is\s+this\?"/);
  }
});

test("the default-model rule points at the Models page and names the settings key defaultModel", () => {
  const block = renderModelContextBlock("vertex/gemini-3.1-pro-preview");
  assert.match(block, /"Set as default" on the Models page/);
  assert.doesNotMatch(block, /geminiModel/);
});

test("the credential guardrail recipe names every model provider", () => {
  const text = buildSystemPromptText(policy);
  assert.match(text, /model provider \(Vertex\s+> AI, Anthropic or OpenAI\)/);
  assert.doesNotMatch(text, /configure your Vertex provider/);
});

test("the rule is still emitted when the model is unknown", () => {
  for (const unknown of [undefined, null, "", "   "]) {
    const block = renderModelContextBlock(unknown);
    assert.doesNotMatch(block, /served by the model/);
    assert.match(block, /Do NOT call `settings_get`/);
  }
});

test("the full prompt carries the block, with the turn's model", () => {
  const text = buildSystemPromptText(policy, null, [], "manual", undefined, "vertex/gemini-3.1-pro-preview");
  assert.match(text, /## CRITICAL - Model in use/);
  assert.match(text, /served by the model `vertex\/gemini-3\.1-pro-preview`/);
});

test("the full prompt without a model still carries the rule", () => {
  const text = buildSystemPromptText(policy);
  assert.match(text, /## CRITICAL - Model in use/);
});

test("the embedder wording is true on an install without Vertex", () => {
  const text = buildSystemPromptText(policy);
  // Embeddings are Vertex-only; without a Vertex provider search runs on a
  // hash-similarity stand-in and does not fail. The prompt must say both, name
  // no embedding model as a fact, and keep the 5xx advice for a failing Vertex.
  assert.doesNotMatch(text, /text-embedding-004/);
  assert.doesNotMatch(text, /no local-ML fallback/i);
  assert.match(text, /hash-similarity\s+stand-in/);
  assert.match(text, /Claude-only or OpenAI-only install/);
  assert.match(text, /embedder_mode/);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
