#!/usr/bin/env node
/**
 * Behaviour test for the agent credential guardrail block of
 * lib/system-prompt.ts: the agent must refuse to change the UI session
 * lifetime (a REST/UI-only security setting) and send the operator to the
 * Session lifetime card on /profile.
 *
 *   node scripts/test-system-prompt-guardrail.mjs   (npm run test:system-prompt-guardrail)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { renderAgentCredentialGuardrailBlock, buildSystemPromptText } = await import("../lib/system-prompt.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("changing the session lifetime is on the refusal list", () => {
  const block = renderAgentCredentialGuardrailBlock();
  assert.match(block, /change\s+the session lifetime/);
});

test("the quoted reply points at the Session lifetime card on /profile", () => {
  const block = renderAgentCredentialGuardrailBlock();
  assert.match(block, /Session lifetime card on \/profile/);
  assert.match(block, /current password/);
});

test("the block is part of the full prompt", () => {
  const text = buildSystemPromptText({ localCategories: [], externalCategories: [], confirmLocalActions: "never" });
  assert.match(text, /Session lifetime card on \/profile/);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
