#!/usr/bin/env node
/**
 * The instance form of every bundle connector (lib/bundle-connector-config.ts,
 * served on the /connectors cards) must describe the same fields as that
 * connector's connector.yaml: every configSchema property and every secretSlot,
 * with the same name, secret-ness, required flag, default and kind of value.
 * A field missing from the card can never be filled in from the UI, and a wrong
 * required flag blocks or lets through a form the connector cannot use.
 *
 *   node scripts/test-bundle-connector-config.mjs   (npm run test:bundle-connector-config)
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import jsYaml from "js-yaml";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { BUNDLE_CONFIG } = await import("../lib/bundle-connector-config.ts");
const connectorsDir = new URL("../../../bundles/spark/connectors/", import.meta.url);
const route = readFileSync(new URL("../app/api/marketplace/connectors/route.ts", import.meta.url), "utf8");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const ids = readdirSync(connectorsDir, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(new URL(`${d.name}/connector.yaml`, connectorsDir)) && !d.name.startsWith("_"))
  .map((d) => d.name)
  .sort();

test("there are nine bundle connectors and the card list has exactly those", () => {
  assert.equal(ids.length, 9, ids.join(", "));
  assert.deepEqual(Object.keys(BUNDLE_CONFIG).sort(), ids);
});

const kind = (type) =>
  type === "secret" || type === "password" ? "secret"
    : type === "boolean" ? "boolean"
      : type === "number" ? "number"
        : type === "array" || type === "multi_select" ? "array"
          : type === "select" || type === "radio" ? "choice"
            : "text";

function yamlKind(prop, isSlot) {
  if (isSlot) return "secret";
  if (Array.isArray(prop.enum) && prop.enum.length) return "choice";
  if (prop.type === "boolean") return "boolean";
  if (prop.type === "integer" || prop.type === "number") return "number";
  if (prop.type === "array") return "array";
  return "text";
}

function yamlDefault(prop) {
  const d = prop.default;
  if (d === undefined || d === null || d === "") return undefined;
  if (Array.isArray(d)) return JSON.stringify(d);
  return String(d);
}

for (const id of ids) {
  const yaml = jsYaml.load(readFileSync(new URL(`${id}/connector.yaml`, connectorsDir), "utf8"));
  const schema = yaml.configSchema ?? {};
  const props = schema.properties ?? {};
  const requiredList = new Set(schema.required ?? []);
  const slots = Object.fromEntries((yaml.secretSlots ?? []).map((s) => [s.name, s]));
  const card = BUNDLE_CONFIG[id] ?? [];
  const byName = Object.fromEntries(card.map((f) => [f.name, f]));

  test(`${id}: the card declares exactly the yaml's properties and secret slots`, () => {
    const want = [...Object.keys(props), ...Object.keys(slots)].sort();
    assert.deepEqual(card.map((f) => f.name).sort(), want);
  });

  test(`${id}: secret-ness, kind of value and default match the yaml`, () => {
    for (const [name, prop] of Object.entries(props)) {
      const f = byName[name];
      assert.ok(f, name);
      assert.equal(kind(f.type), yamlKind(prop, false), `${name} kind (${f.type})`);
      assert.equal(f.defaultValue, yamlDefault(prop), `${name} default`);
      if (Array.isArray(prop.enum)) assert.deepEqual(f.options, prop.enum.map(String), `${name} options`);
    }
    for (const name of Object.keys(slots)) {
      assert.equal(kind(byName[name].type), "secret", `${name} must be a secret field`);
      assert.equal(byName[name].defaultValue, undefined, `${name} has no default`);
    }
  });

  test(`${id}: required flags match the yaml (a field shown only in one mode is checked by its own test)`, () => {
    for (const f of card) {
      if (f.showWhen) continue;
      const want = f.name in slots ? slots[f.name].required === true : requiredList.has(f.name);
      assert.equal(f.required, want, `${f.name} required`);
    }
    // A mode-gated field may be required on the card only when the yaml itself requires nothing for it.
    for (const f of card) if (f.showWhen && f.required) assert.ok(!requiredList.has(f.name), f.name);
  });

  test(`${id}: every field has a label, and a description wherever the yaml has one`, () => {
    for (const f of card) {
      assert.ok(f.display && f.display.trim(), `${f.name} display`);
      const y = f.name in slots ? slots[f.name] : props[f.name];
      if (y && y.description && String(y.description).trim()) assert.ok((f.description ?? "").trim(), `${f.name} description`);
    }
  });

  test(`${id}: route.ts serves this list on the card, with no second copy`, () => {
    assert.ok(route.includes(`config: BUNDLE_CONFIG["${id}"],`));
  });
}

test("route.ts holds no hand-written config list", () => {
  assert.doesNotMatch(route, /\n\s+config: \[\s*(\{|\n)/);
  assert.doesNotMatch(route, /interface ConfigField/);
});

if (failed) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log("\nall passed");
