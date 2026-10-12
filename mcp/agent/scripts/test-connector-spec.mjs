#!/usr/bin/env node
/**
 * Behaviour test for lib/connector-spec.ts (how an uploaded connector.yaml
 * becomes the card and the create-instance form on /connectors).
 *
 *   node scripts/test-connector-spec.mjs   (npm run test:connector-spec)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { toolsFromSpec, configFromSpec, userConnectorCard } = await import("../lib/connector-spec.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

const row = {
  id: "my-conn",
  version: "1.2.0",
  display_name: "My Connector",
  description: "Does a thing.",
  tags: ["a", "b"],
  installed: false,
  origin: "user",
  detail: {
    image: "ghcr.io/example/my-conn:1.2",
    language: "python",
    config_schema: {
      type: "object",
      required: ["baseUrl"],
      properties: {
        baseUrl: { type: "string", widget: "url", description: "Where it lives." },
        retries: { type: "number", default: 3 },
        mode: { type: "string", enum: ["fast", "slow"], default: "fast" },
        verbose: { type: "boolean" },
        empty: { type: "string", default: "" },
      },
    },
    secret_slots: [{ name: "apiKey", description: "Key.", required: true }, { name: "extra" }],
    tools: [
      { name: "echo", method: "GET /echo", description: "Echo it.\nSecond line.", args: [{ name: "msg", type: "string", required: true }] },
      { name: "send", description: "Send." },
      { description: "no name, skipped" },
    ],
  },
};

test("the card reflects the uploaded connector and starts not installed", () => {
  const c = userConnectorCard(row);
  assert.equal(c.id, "my-conn");
  assert.equal(c.name, "My Connector");
  assert.equal(c.origin, "user");
  assert.equal(c.status, "not_installed");
  assert.equal(c.version, "1.2.0");
  assert.equal(c.dockerImage, "ghcr.io/example/my-conn:1.2");
  assert.equal(c.toolCount, 2);
  assert.deepEqual(c.tags, ["a", "b"]);
  assert.equal(userConnectorCard({ ...row, installed: true }).status, "installed");
});

test("tools keep name, verb, first description line and args; unnamed ones are skipped", () => {
  const t = toolsFromSpec(row.detail.tools);
  assert.deepEqual(t.map((x) => [x.name, x.method]), [["echo", "GET"], ["send", "POST"]]);
  assert.equal(t[0].description, "Echo it.");
  assert.deepEqual(t[0].args.map((a) => [a.name, a.required]), [["msg", true]]);
  assert.deepEqual(toolsFromSpec("nope"), []);
});

test("config fields follow the schema: types, required, defaults, options; secret slots become secret fields", () => {
  const f = Object.fromEntries(configFromSpec(row.detail.config_schema, row.detail.secret_slots).map((x) => [x.name, x]));
  assert.equal(f.baseUrl.type, "url");
  assert.equal(f.baseUrl.required, true);
  assert.equal(f.retries.type, "number");
  assert.equal(f.retries.defaultValue, "3");
  assert.equal(f.mode.type, "select");
  assert.deepEqual(f.mode.options, ["fast", "slow"]);
  assert.equal(f.verbose.type, "boolean");
  assert.equal(f.empty.defaultValue, undefined);
  assert.equal(f.apiKey.type, "secret");
  assert.equal(f.apiKey.required, true);
  assert.equal(f.extra.required, false);
});

test("a row without detail still yields a usable card", () => {
  const c = userConnectorCard({ id: "bare" });
  assert.equal(c.name, "bare");
  assert.equal(c.toolCount, 0);
  assert.deepEqual(c.config, []);
  assert.equal(c.authType, "None");
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
