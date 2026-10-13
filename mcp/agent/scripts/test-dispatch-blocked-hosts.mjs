#!/usr/bin/env node
/**
 * The dispatcher builds the Claude and OpenAI adapters with the blocked-host
 * list it is given (the chat route passes the MCP host), so a stored gateway
 * URL that names the MCP is refused for chat the way it is refused on the
 * Providers page and in the connection tests. Also pins that the route passes
 * the list at every model call and that the four former copies of the MCP-host
 * helper are gone.
 *
 *   node scripts/test-dispatch-blocked-hosts.mjs   (npm run test:dispatch-blocked-hosts)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const dispatch = await import("../lib/providers/dispatch.ts");
const { mcpBlockedHosts } = await import("../lib/mcp-host.ts");

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

const MCP_HOST = "mcp.corp.example";
const realFetch = globalThis.fetch;
function trapFetch() {
  const seen = [];
  globalThis.fetch = async (url) => { seen.push(String(url)); throw new Error("the network must not be reached"); };
  return seen;
}

for (const provider of ["anthropic", "openai"]) {
  await test(`${provider}: a stored base URL naming the MCP host is refused before any request`, async () => {
    const seen = trapFetch();
    try {
      const req = { ref: { provider, model: "m" }, system: "S", messages: [{ role: "user", text: "hi" }], tools: [], toolChoice: "none", thinking: false, purpose: "chat" };
      await assert.rejects(
        dispatch.callModel(req, { creds: {} }, {
          blockedHosts: [MCP_HOST],
          resolveCreds: async () => ({ apiKey: "k-test", baseUrl: `https://${MCP_HOST}/v1` }),
        }),
        (e) => e.code === "BASE_URL_REJECTED" && /inside this install/.test(e.message),
      );
      assert.deepEqual(seen, []);
    } finally { globalThis.fetch = realFetch; }
  });

  await test(`${provider}: without the list the same URL is not refused as an install-internal host (why the route must pass it)`, async () => {
    const seen = trapFetch();
    try {
      const req = { ref: { provider, model: "m" }, system: "S", messages: [{ role: "user", text: "hi" }], tools: [], toolChoice: "none", thinking: false, purpose: "chat" };
      await assert.rejects(
        dispatch.callModel(req, { creds: {} }, { resolveCreds: async () => ({ apiKey: "k-test", baseUrl: `https://${MCP_HOST}/v1` }) }),
        (e) => !/inside this install/.test(e.message),
      );
    } finally { globalThis.fetch = realFetch; }
  });

  await test(`${provider}: adapters are cached per list, not shared across lists`, () => {
    const ref = { provider, model: "m" };
    const a = dispatch.resolveAdapter(ref, { blockedHosts: ["a.example"] });
    assert.equal(dispatch.resolveAdapter(ref, { blockedHosts: ["a.example"] }), a, "same list, same adapter");
    assert.notEqual(dispatch.resolveAdapter(ref, { blockedHosts: ["b.example"] }), a, "another list, another adapter");
    assert.equal(dispatch.resolveAdapter(ref), dispatch.resolveAdapter(ref, { blockedHosts: [] }));
  });
}

await test("mcpBlockedHosts reads MCP_URL at call time and survives a bad value", () => {
  const prior = process.env.MCP_URL;
  try {
    process.env.MCP_URL = "https://mcp.corp.example:8443/api/v1/stream/mcp";
    assert.deepEqual(mcpBlockedHosts(), ["mcp.corp.example"]);
    process.env.MCP_URL = "not a url";
    assert.deepEqual(mcpBlockedHosts(), []);
    delete process.env.MCP_URL;
    assert.deepEqual(mcpBlockedHosts(), ["localhost"]);
  } finally { if (prior === undefined) delete process.env.MCP_URL; else process.env.MCP_URL = prior; }
});

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel) => readFileSync(join(root, rel), "utf8");

await test("the chat route passes the blocked hosts at every model call", () => {
  const src = read("app/api/chat/route.ts");
  assert.equal([...src.matchAll(/modelDispatchDeps\(\)/g)].length, 4, "three call sites plus the helper's own definition line");
  assert.match(src, /function modelDispatchDeps\(\): DispatchDeps \{\n  return \{ blockedHosts: mcpBlockedHosts\(\) \};/);
});

await test("the MCP-host helper has one home", () => {
  for (const rel of ["app/api/agent/providers/anthropic/test/route.ts", "app/api/agent/providers/openai/test/route.ts", "app/api/agent/providers/config/route.ts", "lib/model-registry-server.ts"]) {
    const src = read(rel);
    assert.doesNotMatch(src, /function mcpHosts?\(/, `${rel} still defines its own copy`);
    assert.match(src, /mcpBlockedHosts\(\)/, `${rel} uses the shared helper`);
  }
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall dispatch blocked-host tests passed");
