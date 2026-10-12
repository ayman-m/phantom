#!/usr/bin/env node
/**
 * Every skill the system prompt points the agent at must exist on disk.
 *
 * The prompt used to name skills that no longer ship (port_scan,
 * ransomware_attack, credential_theft_apt, generate_shared_iocs, ...); the
 * agent then called skills_read on a path that 404s. This test pulls each
 * `<category>/<name>.md` path out of the assembled prompt and checks it against
 * bundles/spark/mcp/skills, and pins the retired names so they cannot return.
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-system-prompt-skill-names.mjs   (npm run test:system-prompt-skill-names)
 */
import assert from "node:assert/strict";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const here = path.dirname(fileURLToPath(import.meta.url));
const skillsDir = path.resolve(here, "../../../bundles/spark/mcp/skills");
const { buildSystemPromptText } = await import("../lib/system-prompt.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const policy = { localCategories: [], externalCategories: [], confirmLocalActions: "never" };
const text = buildSystemPromptText(policy);

test("the skills directory is where the test expects it", () => {
  assert.ok(existsSync(path.join(skillsDir, "scenarios")), skillsDir);
  assert.ok(readdirSync(path.join(skillsDir, "scenarios")).length > 0);
});

test("every skill path named in the prompt exists on disk", () => {
  const paths = [...new Set(text.match(/\b(?:foundation|scenarios|validation|workflows)\/[A-Za-z0-9_]+\.md\b/g) ?? [])];
  assert.ok(paths.length >= 5, "expected the prompt to name several skills, found " + paths.length);
  const missing = paths.filter((p) => !existsSync(path.join(skillsDir, p)));
  assert.deepEqual(missing, [], "skill paths in the prompt that do not exist: " + missing.join(", "));
});

test("retired skill names are gone from the prompt", () => {
  const retired = [
    "ransomware_attack",
    "credential_theft_apt",
    "ransomware_double_extortion",
    "generate_shared_iocs",
    "create_device_topology",
    "DEVICE_VENDOR_CATALOG",
    "AUTHENTICATION_FIELDS_GUIDE",
    "port_scan skill",
  ];
  for (const name of retired) assert.ok(!text.includes(name), "retired name still in the prompt: " + name);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
