#!/usr/bin/env node
/**
 * Behaviour test for lib/connector-form.ts: which fields the instance form
 * shows (showWhen), what is required, what Edit starts from (every declared
 * field and secret slot, the destination mode inferred for an older http-sender
 * instance) and what Create and Edit send.
 *
 *   node scripts/test-connector-form.mjs   (npm run test:connector-form)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import jsYaml from "js-yaml";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const {
  MASK, isVisible, visibleParams, missingRequired, inferDestinationMode,
  seedEditValues, buildCreatePayload, buildEditPayload, valueOf, typedValue, invalidNumbers,
} = await import("../lib/connector-form.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

// The real http-sender card, not a copy (lib/bundle-connector-config.ts feeds the /connectors forms).
const { BUNDLE_CONFIG } = await import("../lib/bundle-connector-config.ts");
const params = BUNDLE_CONFIG["http-sender"];
const byName = (name) => params.find((p) => p.name === name);
const names = (list) => list.map((p) => p.name);
const COMMON = ["userDomain", "verifyTls", "timeoutSeconds"];
const HTTP_FIELDS = ["collectorUrl", "vendor", "product", "collectorKey", "additionalDestinations", "additionalKeys"];
const CRIBL_FIELDS = ["criblUrl", "criblToken", "criblIntegration", "windowsDnsSuffix"];
const inOrder = (shown) => params.map((p) => p.name).filter((n) => shown.includes(n));

test("the mode defaults to http before anything is typed, so only the HTTP fields show", () => {
  assert.deepEqual(names(visibleParams(params, {})), inOrder(["destinationMode", ...HTTP_FIELDS, ...COMMON]));
});

test("cribl shows the Cribl fields and none of the HTTP ones", () => {
  assert.deepEqual(
    names(visibleParams(params, { destinationMode: "cribl" })),
    inOrder(["destinationMode", ...CRIBL_FIELDS, ...COMMON]),
  );
});

test("both shows every field", () => {
  assert.equal(visibleParams(params, { destinationMode: "both" }).length, params.length);
});

test("a field with no showWhen is always visible, and an unknown controller value hides", () => {
  assert.ok(isVisible(byName("userDomain"), params, { destinationMode: "cribl" }));
  assert.ok(!isVisible(byName("collectorUrl"), params, { destinationMode: "nonsense" }));
});

test("a controller that is not in the list reads the raw value", () => {
  const p = { name: "x", type: "string", required: true, showWhen: { field: "gone", in: ["a"] } };
  assert.ok(isVisible(p, [p], { gone: "a" }));
  assert.ok(!isVisible(p, [p], {}));
});

test("required fields are only the visible ones", () => {
  assert.deepEqual(names(missingRequired(params, {})), ["collectorUrl", "vendor", "product", "collectorKey"]);
  assert.deepEqual(names(missingRequired(params, { destinationMode: "cribl" })), ["criblUrl", "criblToken"]);
  assert.deepEqual(
    names(missingRequired(params, { destinationMode: "both" })),
    ["collectorUrl", "vendor", "product", "collectorKey", "criblUrl", "criblToken"],
  );
});

test("filling the visible required fields satisfies the check, whatever the hidden ones hold", () => {
  const values = { destinationMode: "cribl", criblUrl: "https://api-lab.example/logs/v1/integrated/cribl/data", criblToken: "t" };
  assert.deepEqual(missingRequired(params, values), []);
});

test("a stored secret counts as filled, a default counts, blank spaces do not", () => {
  assert.deepEqual(names(missingRequired(params, { destinationMode: "cribl", criblUrl: "https://x" }, ["criblToken"])), []);
  assert.deepEqual(names(missingRequired(params, { destinationMode: "cribl", criblUrl: "  ", criblToken: "t" })), ["criblUrl"]);
  assert.equal(valueOf(byName("userDomain"), {}), "phantom-lab.example");
});

test("mode inference: both sides is both, only the Cribl side is cribl, anything else is http", () => {
  const tok = { criblToken: MASK };
  assert.equal(inferDestinationMode({ collectorUrl: "https://a", criblUrl: "https://b" }, tok), "both");
  assert.equal(inferDestinationMode({ criblUrl: "https://b" }, tok), "cribl");
  assert.equal(inferDestinationMode({ collectorUrl: "https://a" }, tok), "http");
  assert.equal(inferDestinationMode({}), "http");
  assert.equal(inferDestinationMode({ collectorUrl: " ", criblUrl: "https://b" }, tok), "cribl");
});

test("additional destinations are collector-side config, so a Cribl URL with them is both", () => {
  const tok = { criblToken: MASK };
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: '[{"url":"https://c"}]' }, tok), "both");
  assert.equal(inferDestinationMode({ additionalDestinations: '[{"url":"https://c"}]' }), "http");
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: "  " }, tok), "cribl");
});

test("a Cribl URL with no saved Cribl token is half-configured and does not open as cribl or both", () => {
  assert.equal(inferDestinationMode({ criblUrl: "https://b" }, {}), "http");
  assert.equal(inferDestinationMode({ collectorUrl: "https://a", criblUrl: "https://b" }, { collectorKey: MASK }), "http");
  const saved = { config: { collectorUrl: "https://a", vendor: "Okta", product: "SSO", criblUrl: "https://b" }, secrets: { collectorKey: MASK } };
  const values = seedEditValues("http-sender", params, saved);
  assert.equal(values.destinationMode, "http");
  assert.deepEqual(missingRequired(params, values, ["collectorKey"]), [], "Save is not blocked");
});

test("an empty additionalDestinations list does not make an instance collector-side", () => {
  const tok = { criblToken: MASK };
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: "[]" }, tok), "cribl");
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: " [ ] " }, tok), "cribl");
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: "not json" }, tok), "cribl");
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: '{"a":1}' }, tok), "cribl");
  assert.equal(inferDestinationMode({ criblUrl: "https://b", additionalDestinations: [{ url: "https://c" }] }, tok), "both");
});

// Connectors read number settings with int() or float(), which raise on "" and "30s".
test("a number field holding text is invalid, an empty one is not", () => {
  const web = BUNDLE_CONFIG.web;
  assert.deepEqual(invalidNumbers(web, { cdp_url: "x", default_timeout_ms: "30s" }).map((p) => p.name), ["default_timeout_ms"]);
  assert.deepEqual(invalidNumbers(web, { default_timeout_ms: "" }), []);
  assert.deepEqual(invalidNumbers(web, { default_timeout_ms: " 1500 " }), []);
  assert.deepEqual(invalidNumbers(web, { default_timeout_ms: "1.5" }), []);
  assert.deepEqual(invalidNumbers(web, {}), [], "the default is a number");
  assert.deepEqual(invalidNumbers(params, { destinationMode: "cribl", timeoutSeconds: "soon" }).map((p) => p.name), ["timeoutSeconds"]);
  const hidden = [{ name: "n", type: "number", required: false, showWhen: { field: "m", in: ["a"] } }];
  assert.deepEqual(invalidNumbers(hidden, { m: "b", n: "x" }), [], "a hidden field is not checked");
});

test("an empty number field is left out of Create and Edit, even when one was saved", () => {
  const xdr = BUNDLE_CONFIG["cortex-xdr"];
  const created = buildCreatePayload(xdr, { api_url: "https://api-lab.example", api_id: "1", pollIntervalSeconds: "", maxPollAttempts: "  " });
  assert.ok(!("pollIntervalSeconds" in created.config) && !("maxPollAttempts" in created.config));
  const saved = { config: { api_url: "https://api-lab.example", api_id: "1", pollIntervalSeconds: 5 }, secrets: { api_key: MASK } };
  const values = seedEditValues("cortex-xdr", xdr, saved);
  assert.equal(buildEditPayload(xdr, values, saved).config.pollIntervalSeconds, 5);
  values.pollIntervalSeconds = "";
  assert.ok(!("pollIntervalSeconds" in buildEditPayload(xdr, values, saved).config));
  values.pollIntervalSeconds = "   ";
  assert.ok(!("pollIntervalSeconds" in buildEditPayload(xdr, values, saved).config));
});

test("Edit starts from every declared field, the saved config and the masked slots", () => {
  const values = seedEditValues("http-sender", params, {
    config: { collectorUrl: "https://a", vendor: "Okta", product: "SSO", timeoutSeconds: 30 },
    secrets: { collectorKey: MASK },
  });
  assert.equal(values.collectorUrl, "https://a");
  assert.equal(values.timeoutSeconds, "30");
  assert.equal(values.collectorKey, MASK);
  assert.equal(values.criblToken, undefined, "a slot never set stays empty so it can be filled in");
  assert.equal(values.userDomain, "phantom-lab.example");
  assert.equal(values.destinationMode, "http");
});

test("Edit infers the mode of an older instance, and keeps a saved one", () => {
  const cribl = seedEditValues("http-sender", params, { config: { criblUrl: "https://b" }, secrets: { criblToken: MASK } });
  assert.equal(cribl.destinationMode, "cribl");
  const both = seedEditValues("http-sender", params, { config: { collectorUrl: "https://a", criblUrl: "https://b" }, secrets: { criblToken: MASK } });
  assert.equal(both.destinationMode, "both");
  const saved = seedEditValues("http-sender", params, { config: { destinationMode: "both" }, secrets: {} });
  assert.equal(saved.destinationMode, "both");
  const other = seedEditValues("xlog", [{ name: "u", type: "url", required: true }], { config: { criblUrl: "x" }, secrets: {} });
  assert.equal(other.destinationMode, undefined, "only http-sender gets a mode");
});

test("Create in http mode sends the HTTP fields and no Cribl ones, even if some were typed first", () => {
  const sent = buildCreatePayload(params, {
    destinationMode: "http", collectorUrl: "https://a", vendor: "Okta", product: "SSO", collectorKey: "k1",
    criblUrl: "https://b", criblToken: "t1", criblIntegration: "x", userDomain: "phantom-lab.example", timeoutSeconds: "15", verifyTls: "true",
  });
  assert.deepEqual(sent.config, {
    destinationMode: "http", collectorUrl: "https://a", vendor: "Okta", product: "SSO",
    userDomain: "phantom-lab.example", timeoutSeconds: 15, verifyTls: true,
  });
  assert.deepEqual(sent.secrets, { collectorKey: "k1" });
});

test("Create in cribl mode sends the Cribl fields and no collector URL, vendor or product", () => {
  const sent = buildCreatePayload(params, {
    destinationMode: "cribl", collectorUrl: "https://a", vendor: "Okta", product: "SSO", collectorKey: "k1",
    criblUrl: "https://b", criblToken: "t1", criblIntegration: "phantom-http-sender",
  });
  assert.deepEqual(sent.config, { destinationMode: "cribl", criblUrl: "https://b", criblIntegration: "phantom-http-sender" });
  assert.deepEqual(sent.secrets, { criblToken: "t1" });
});

test("Create drops empty values", () => {
  const sent = buildCreatePayload(params, { destinationMode: "http", collectorUrl: "https://a", vendor: "", collectorKey: "" });
  assert.deepEqual(sent.config, { destinationMode: "http", collectorUrl: "https://a" });
  assert.deepEqual(sent.secrets, {});
});

const savedHttp = {
  config: { collectorUrl: "https://a", vendor: "Okta", product: "SSO", additionalDestinations: "[]", extra_flag: "keep-me" },
  secrets: { collectorKey: MASK },
};

test("Edit adds the Cribl endpoint to an HTTP-only instance: the token is a new secret, the collector key is kept", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  values.destinationMode = "both";
  values.criblUrl = "https://b";
  values.criblToken = "t1";
  const sent = buildEditPayload(params, values, savedHttp);
  assert.equal(sent.config.criblUrl, "https://b");
  assert.equal(sent.config.collectorUrl, "https://a");
  assert.equal(sent.config.destinationMode, "both");
  assert.deepEqual(sent.secrets, { collectorKey: MASK, criblToken: "t1" });
});

test("Edit does not add never-saved fields that were left at their defaults", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  const sent = buildEditPayload(params, values, savedHttp);
  for (const k of ["userDomain", "timeoutSeconds", "verifyTls", "criblIntegration", "windowsDnsSuffix", "destinationMode", "criblUrl"]) {
    assert.ok(!(k in sent.config), k + " was never saved and was not touched");
  }
  assert.deepEqual(Object.keys(sent.config).sort(), ["additionalDestinations", "collectorUrl", "extra_flag", "product", "vendor"]);
});

test("Edit sends a never-saved field once the operator changes it", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  values.timeoutSeconds = "30";
  assert.equal(buildEditPayload(params, values, savedHttp).config.timeoutSeconds, 30);
});

test("Edit leaves out a slot that was never set and was not touched, and never sends an empty secret", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  const sent = buildEditPayload(params, values, savedHttp);
  assert.deepEqual(sent.secrets, { collectorKey: MASK });
  values.collectorKey = "";
  assert.deepEqual(buildEditPayload(params, values, savedHttp).secrets, { collectorKey: MASK });
  values.criblToken = "";
  assert.ok(!("criblToken" in buildEditPayload(params, values, savedHttp).secrets));
});

test("Edit rotates a secret that is typed over", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  values.collectorKey = "rotated";
  assert.equal(buildEditPayload(params, values, savedHttp).secrets.collectorKey, "rotated");
});

test("Edit in http mode sends criblUrl empty, and cribl mode clears the collector routing", () => {
  const savedBoth = {
    config: { destinationMode: "both", collectorUrl: "https://a", vendor: "Okta", product: "SSO", additionalDestinations: "[{}]", criblUrl: "https://b" },
    secrets: { collectorKey: MASK, criblToken: MASK },
  };
  const toHttp = seedEditValues("http-sender", params, savedBoth);
  toHttp.destinationMode = "http";
  const http = buildEditPayload(params, toHttp, savedBoth);
  assert.equal(http.config.criblUrl, "");
  assert.equal(http.config.collectorUrl, "https://a");
  assert.deepEqual(http.secrets, { collectorKey: MASK, criblToken: MASK }, "secrets are never cleared");

  const toCribl = seedEditValues("http-sender", params, savedBoth);
  toCribl.destinationMode = "cribl";
  const cribl = buildEditPayload(params, toCribl, savedBoth);
  assert.equal(cribl.config.collectorUrl, "");
  assert.equal(cribl.config.vendor, "");
  assert.equal(cribl.config.product, "");
  assert.equal(cribl.config.additionalDestinations, "");
  assert.equal(cribl.config.criblUrl, "https://b");
});

test("Edit keeps a hidden field's value when it is not marked clearWhenHidden", () => {
  const saved = { config: { destinationMode: "http", collectorUrl: "https://a", criblIntegration: "my-name" }, secrets: {} };
  const values = seedEditValues("http-sender", params, saved);
  assert.equal(buildEditPayload(params, values, saved).config.criblIntegration, "my-name");
});

test("Edit sends every saved key again, including ones the card does not declare", () => {
  const values = seedEditValues("http-sender", params, savedHttp);
  assert.equal(buildEditPayload(params, values, savedHttp).config.extra_flag, "keep-me");
  values.extra_flag = "edited";
  assert.equal(buildEditPayload(params, values, savedHttp).config.extra_flag, "edited");
});

test("a connector with no card fields falls back to the saved keys: secrets by slot, config as typed", () => {
  const saved = { config: { baseUrl: "https://x", apiKey: "plain" }, secrets: { token: MASK } };
  const values = seedEditValues("my-conn", [], saved);
  assert.deepEqual(values, { baseUrl: "https://x", apiKey: "plain", token: MASK });
  values.baseUrl = "https://y";
  const sent = buildEditPayload([], values, saved);
  assert.deepEqual(sent.config, { baseUrl: "https://y" });
  assert.deepEqual(sent.secrets, { apiKey: "plain", token: MASK });
});

test("a saved value that is not a string goes back with its type unless it is edited", () => {
  const saved = { config: { trusted: true, retries: 3, note: "x" }, secrets: {} };
  const values = seedEditValues("my-conn", [], saved);
  assert.deepEqual(values, { trusted: "true", retries: "3", note: "x" });
  assert.deepEqual(buildEditPayload([], values, saved).config, { trusted: true, retries: 3, note: "x" });
  values.retries = "5";
  assert.deepEqual(buildEditPayload([], values, saved).config, { trusted: true, retries: "5", note: "x" });
  const declared = [{ name: "retries", type: "number", required: false, defaultValue: "1" }];
  assert.equal(buildEditPayload(declared, seedEditValues("my-conn", declared, saved), saved).config.retries, 3);
});

test("an Edit field that was empty and stays empty is not invented", () => {
  const p = [{ name: "note", type: "string", required: false }];
  assert.deepEqual(buildEditPayload(p, {}, { config: {}, secrets: {} }).config, {});
  assert.deepEqual(buildEditPayload(p, { note: "" }, { config: { note: "old" }, secrets: {} }).config, { note: "" });
});

// The web connector turns allowed_domains into a list with list(), which splits the
// string '["a.example"]' into characters and then blocks every navigation. So lists go
// as real arrays.
test("array fields go as real arrays in Create and Edit, and the empty default is an empty list", () => {
  const web = BUNDLE_CONFIG.web;
  const created = buildCreatePayload(web, {
    cdp_url: "http://phantom-browser:9222", default_timeout_ms: "30000",
    allowed_domains: '["intel.example",".vendor.example"]', block_resource_types: "[]",
  });
  assert.deepEqual(created.config.allowed_domains, ["intel.example", ".vendor.example"]);
  assert.deepEqual(created.config.block_resource_types, []);
  assert.equal(created.config.default_timeout_ms, 30000);

  const saved = { config: { cdp_url: "http://phantom-browser:9222", allowed_domains: '["a.example"]' }, secrets: {} };
  const values = seedEditValues("web", web, saved);
  const sent = buildEditPayload(web, values, saved);
  assert.deepEqual(sent.config.allowed_domains, ["a.example"], "a list an older save stored as text is repaired");
  assert.ok(!("block_resource_types" in sent.config), "a never-saved list left at its default is not written");
  assert.ok(!("default_timeout_ms" in sent.config));
});

test("boolean and number text becomes real booleans and numbers, other text stays text", () => {
  assert.equal(typedValue("boolean", "true"), true);
  assert.equal(typedValue("boolean", "false"), false);
  assert.equal(typedValue("boolean", "maybe"), "maybe");
  assert.equal(typedValue("number", "15"), 15);
  assert.equal(typedValue("number", "1.5"), 1.5);
  assert.equal(typedValue("number", "soon"), "soon");
  assert.deepEqual(typedValue("array", '["a"]'), ["a"]);
  assert.equal(typedValue("array", "a, b"), "a, b");
  assert.equal(typedValue("string", "15"), "15");
});

// The card must describe the same form as connector.yaml.
test("the http-sender card matches connector.yaml: mode switch, defaults and per-mode requirements", async () => {
  const yaml = jsYaml.load(readFileSync(new URL("../../../bundles/spark/connectors/http-sender/connector.yaml", import.meta.url), "utf8"));
  const props = yaml.configSchema.properties;
  assert.ok(!yaml.configSchema.required, "the schema requires nothing itself: the requirements depend on the mode");
  const mode = byName("destinationMode");
  assert.deepEqual(mode.options, props.destinationMode.enum);
  assert.equal(mode.defaultValue, props.destinationMode.default);
  assert.deepEqual(Object.keys(mode.optionLabels).sort(), [...props.destinationMode.enum].sort());

  const HTTP = { field: "destinationMode", in: ["http", "both"] };
  const CRIBL = { field: "destinationMode", in: ["cribl", "both"] };
  const expected = {
    collectorUrl: { showWhen: HTTP, clearWhenHidden: true, required: true },
    vendor: { showWhen: HTTP, clearWhenHidden: true, required: true },
    product: { showWhen: HTTP, clearWhenHidden: true, required: true },
    collectorKey: { showWhen: HTTP, clearWhenHidden: undefined, required: true },
    additionalDestinations: { showWhen: HTTP, clearWhenHidden: true, required: false },
    additionalKeys: { showWhen: HTTP, clearWhenHidden: undefined, required: false },
    criblUrl: { showWhen: CRIBL, clearWhenHidden: true, required: true },
    criblToken: { showWhen: CRIBL, clearWhenHidden: undefined, required: true },
    criblIntegration: { showWhen: CRIBL, clearWhenHidden: undefined, required: false },
    windowsDnsSuffix: { showWhen: CRIBL, clearWhenHidden: undefined, required: false },
    userDomain: { showWhen: undefined, clearWhenHidden: undefined, required: false },
    verifyTls: { showWhen: undefined, clearWhenHidden: undefined, required: false },
    timeoutSeconds: { showWhen: undefined, clearWhenHidden: undefined, required: false },
  };
  for (const [name, want] of Object.entries(expected)) {
    const p = byName(name);
    assert.ok(p, name + " is on the card");
    assert.deepEqual(p.showWhen, want.showWhen, name + " showWhen");
    assert.equal(p.clearWhenHidden, want.clearWhenHidden, name + " clearWhenHidden");
    assert.equal(p.required, want.required, name + " required");
  }
  assert.equal(params.length, Object.keys(expected).length + 1, "no field on the card is unaccounted for");

  // Every field the card requires is gated by the mode (the yaml requires none), and every routing
  // field (a URL, vendor, product or the extra-collector list) is cleared when its mode is hidden.
  for (const p of params) {
    if (p.name !== "destinationMode" && p.required) assert.ok(p.showWhen, p.name + " is required only in its mode");
  }
  for (const name of ["collectorUrl", "vendor", "product", "additionalDestinations", "criblUrl"]) {
    assert.equal(byName(name).clearWhenHidden, true, name + " must be cleared when hidden");
  }
  // The yaml's secret slots are the card's secret fields, and the slots are optional there.
  const slots = Object.fromEntries(yaml.secretSlots.map((s) => [s.name, s]));
  for (const p of params.filter((q) => q.type === "secret")) assert.ok(slots[p.name], p.name + " is a yaml secret slot");
  for (const name of Object.keys(slots)) assert.equal(byName(name).type, "secret", name + " is a secret on the card");
  for (const s of Object.values(slots)) assert.equal(s.required, false, s.name + " is required by mode, not by the yaml");
  for (const [name, prop] of Object.entries(props)) {
    const card = byName(name);
    const dflt = prop.default === undefined || prop.default === null || prop.default === "" ? undefined : String(prop.default);
    assert.equal(card.defaultValue, dflt, name + " default");
  }
});

if (failed) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log("\nall passed");
