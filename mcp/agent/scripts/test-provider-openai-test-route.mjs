#!/usr/bin/env node
/**
 * POST /api/agent/providers/openai/test: runs the real route handler (and
 * lib/providers/connection-test.ts behind it) against stubbed Next, MCP-proxy
 * and DNS modules and a fake network, and asserts:
 *
 *   - the sentinel "***" (or an empty key) tests the SAVED key, resolved on the
 *     server, and only against the base URL it was saved with;
 *   - a typed key is tested as typed, against the form's base URL;
 *   - every answer is HTTP 200 {status, message, modelCount?};
 *   - one `provider_test` audit row per test, never carrying the key;
 *   - an unsafe base URL never reaches the network;
 *   - the route is under the credential prefix, so API keys get 403.
 *
 *   node scripts/test-provider-openai-test-route.mjs   (npm run test:provider-openai-test-route)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the route).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as nodeModule from "node:module";

if (!process.features.typescript || typeof nodeModule.stripTypeScriptTypes !== "function" || typeof nodeModule.registerHooks !== "function") {
  console.log("skip: this Node lacks type stripping or module hooks");
  process.exit(0);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dataModule = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

const STUBS = {
  "next/server": dataModule(`export const NextResponse = { json(body, init) { return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } }); } };`),
  "@/lib/mcp-proxy": dataModule(`export async function callMcpServer(path, init) { globalThis.__audits.push({ path, init }); return {}; }`),
  "node:dns/promises": dataModule(`export async function lookup(host) { return [{ address: globalThis.__dns?.[host] ?? '203.0.113.10', family: 4 }]; }`),
};

nodeModule.registerHooks({
  resolve(specifier, context, nextResolve) {
    if (STUBS[specifier]) return { url: STUBS[specifier], shortCircuit: true };
    if (specifier.startsWith("@/")) {
      const rel = specifier.slice(2);
      const file = /\.[cm]?[jt]sx?$/.test(rel) ? rel : `${rel}.ts`;
      return { url: pathToFileURL(join(root, file)).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

globalThis.__audits = [];
globalThis.__dns = {};
process.env.MCP_TOKEN = "tok-fake";
process.env.MCP_URL = "http://localhost:8080/api/v1/stream/mcp";

const route = await import("../app/api/agent/providers/openai/test/route.ts");
const creds = await import("../lib/providers/credentials.ts");
const scopes = await import("../lib/agent-scopes.ts");

let failed = 0;
const queue = [];
const test = (name, fn) => queue.push({ name, fn });

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const K_SAVED = ["sk", "proj", "SAVED" + "x".repeat(16)].join("-");
const K_TYPED = ["sk", "proj", "TYPED" + "y".repeat(16)].join("-");

const MODELS = { object: "list", data: [{ id: "gpt-6-sol" }, { id: "gpt-6-luna" }, { id: "text-embedding-3-small" }] };

/** A fake network: the MCP provider store plus the OpenAI API. */
function installNetwork({ saved, vendor = () => new Response(JSON.stringify(MODELS), { status: 200, headers: { "content-type": "application/json" } }) } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    calls.push({ host: u.host, url: String(url), init });
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    if (u.host === "localhost:8080") {
      if (u.pathname === "/api/v1/providers") return json({ instances: saved ? [{ id: "openai-1", provider_id: "openai" }] : [] });
      return json({ instance: { id: "openai-1", provider_id: "openai", ...saved } });
    }
    return vendor(u, init);
  };
  return calls;
}

function reset() {
  creds.bustProviderCredsCache();
  globalThis.__audits = [];
  globalThis.__dns = {};
}

async function post(body) {
  const res = await route.POST(new Request("http://localhost/api/agent/providers/openai/test", { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) }));
  assert.equal(res.status, 200, "a test always answers HTTP 200");
  return await res.json();
}
const vendorCalls = (calls) => calls.filter((c) => c.host !== "localhost:8080");
const auditRows = () => globalThis.__audits.filter((a) => a.path === "/api/v1/audit").map((a) => a.init.body);

test("the route exports only POST and dynamic, and sits under the credential prefix (API keys get 403)", () => {
  const src = readFileSync(join(root, "app/api/agent/providers/openai/test/route.ts"), "utf8");
  const exports = [...src.matchAll(/^export\s+(?:async\s+)?(?:const|function)\s+(\w+)/gm)].map((m) => m[1]).sort();
  assert.deepEqual(exports, ["POST", "dynamic"]);
  const path = "/api/agent/providers/openai/test";
  assert.equal(scopes.isCredentialRoute(path), true, "middleware refuses an API key on this path whatever its scope");
  assert.equal(scopes.isCredentialRoute("/api/agent/providers/openai/test"), true);
  assert.equal(scopes.isCredentialRoute("/api/agent/models"), false, "control: the models list stays open to read keys");
});

test('"***" tests the saved key, resolved on the server, against the default base URL', async () => {
  reset();
  const calls = installNetwork({ saved: { config: {}, secrets: { api_key: K_SAVED } } });
  const body = await post({ api_key: "***", base_url: "" });
  assert.equal(body.status, "success");
  assert.equal(body.modelCount, 3);
  assert.match(body.message, /3 models visible, including GPT-6 Sol, GPT-6 Luna/);
  const v = vendorCalls(calls);
  assert.equal(v.length, 1);
  assert.match(v[0].url, /^https:\/\/api\.openai\.com\/v1\/models$/);
  assert.equal(v[0].init.headers.Authorization, `Bearer ${K_SAVED}`);
  assert.ok(!JSON.stringify(body).includes(K_SAVED), "the key is never returned");
});

test("an empty or missing api_key also means the saved key", async () => {
  for (const payload of [{ api_key: "" }, {}, { api_key: "   " }]) {
    reset();
    const calls = installNetwork({ saved: { config: {}, secrets: { api_key: K_SAVED } } });
    const body = await post(payload);
    assert.equal(body.status, "success", JSON.stringify(payload));
    assert.equal(vendorCalls(calls)[0].init.headers.Authorization, `Bearer ${K_SAVED}`);
  }
});

test('"***" with no saved key is an error and reaches no vendor', async () => {
  reset();
  const calls = installNetwork({});
  const body = await post({ api_key: "***" });
  assert.equal(body.status, "error");
  assert.match(body.message, /No OpenAI API key is saved yet/);
  assert.equal(vendorCalls(calls).length, 0);
  assert.equal(auditRows().length, 0, "nothing was tested, so nothing is audited");
});

test('the saved key goes only to the base URL it was saved with: "***" plus a different base URL is refused', async () => {
  reset();
  const calls = installNetwork({ saved: { config: { base_url: "https://llm.gateway.example.com/openai/v1" }, secrets: { api_key: K_SAVED } } });
  const refused = await post({ api_key: "***", base_url: "https://other.example.com" });
  assert.equal(refused.status, "error");
  assert.match(refused.message, /only used with the base URL it was saved with/);
  const toDefault = await post({ api_key: "***", base_url: "https://api.openai.com/v1" });
  assert.equal(toDefault.status, "error", "the default is also a different host from the saved gateway");
  assert.equal(vendorCalls(calls).length, 0, "the saved key never left");
  // The same URL, however it is spelled, is accepted and uses the saved base.
  const same = await post({ api_key: "***", base_url: "HTTPS://LLM.Gateway.Example.com/openai/v1/" });
  assert.equal(same.status, "success");
  assert.match(vendorCalls(calls)[0].url, /^https:\/\/llm\.gateway\.example\.com\/openai\/v1\/models$/);
  // Leaving the field empty keeps the saved base.
  const blank = await post({ api_key: "***", base_url: "" });
  assert.equal(blank.status, "success");
  assert.match(vendorCalls(calls)[1].url, /^https:\/\/llm\.gateway\.example\.com\/openai\/v1\/models$/);
});

test("a typed key is tested as typed against the form's base URL, ignoring what is saved", async () => {
  reset();
  const calls = installNetwork({ saved: { config: { base_url: "https://llm.gateway.example.com" }, secrets: { api_key: K_SAVED } } });
  const body = await post({ api_key: K_TYPED, base_url: "https://other.example.com" });
  assert.equal(body.status, "success");
  const v = vendorCalls(calls);
  assert.equal(v[0].host, "other.example.com");
  assert.equal(v[0].init.headers.Authorization, `Bearer ${K_TYPED}`);
  assert.equal(calls.filter((c) => c.host === "localhost:8080").length, 0, "the store is not consulted for a typed key");
  const dflt = await post({ api_key: K_TYPED });
  assert.equal(dflt.status, "success");
  assert.equal(vendorCalls(calls)[1].host, "api.openai.com", "an empty base URL means the default");
});

test("a rejected key is reported with OpenAI's own message, redacted, still HTTP 200", async () => {
  reset();
  installNetwork({ vendor: () => new Response(JSON.stringify({ error: { type: "invalid_request_error", code: "invalid_api_key", message: `Incorrect API key provided: ${K_TYPED}` } }), { status: 401, headers: { "content-type": "application/json", "x-request-id": "req_x" } }) });
  const body = await post({ api_key: K_TYPED });
  assert.equal(body.status, "error");
  assert.match(body.message, /Incorrect API key provided/);
  assert.ok(!body.message.includes(K_TYPED));
  assert.match(body.message, /401/);
});

test("organization and project from the form are sent as headers, with a typed key and with the saved key", async () => {
  reset();
  const calls = installNetwork({ saved: { config: { organization: "org-saved1", project: "proj_saved1" }, secrets: { api_key: K_SAVED } } });
  const typed = await post({ api_key: K_TYPED, organization: "org-form1", project: "proj_form1" });
  assert.equal(typed.status, "success");
  let h = vendorCalls(calls)[0].init.headers;
  assert.equal(h["OpenAI-Organization"], "org-form1");
  assert.equal(h["OpenAI-Project"], "proj_form1");
  // With the saved key, the form's values win over the saved ones; they only choose the account on the same host.
  const saved = await post({ api_key: "***", organization: "org-form2", project: "" });
  assert.equal(saved.status, "success");
  h = vendorCalls(calls)[1].init.headers;
  assert.equal(h.Authorization, `Bearer ${K_SAVED}`);
  assert.equal(h["OpenAI-Organization"], "org-form2");
  assert.equal("OpenAI-Project" in h, false, "an empty value clears the saved one");
  // Absent fields keep the saved values.
  const keep = await post({ api_key: "***" });
  assert.equal(keep.status, "success");
  h = vendorCalls(calls)[2].init.headers;
  assert.equal(h["OpenAI-Organization"], "org-saved1");
  assert.equal(h["OpenAI-Project"], "proj_saved1");
});

test("a header-injection attempt in organization or project never reaches a header", async () => {
  reset();
  const calls = installNetwork({});
  await post({ api_key: K_TYPED, organization: "org-x\r\nX-Evil: 1", project: "proj y" });
  const h = vendorCalls(calls)[0].init.headers;
  assert.equal("OpenAI-Organization" in h, false);
  assert.equal("OpenAI-Project" in h, false);
  assert.equal("X-Evil" in h, false);
});

test("the saved key is not sent to a base URL that only differs by the /v1 segment", async () => {
  reset();
  const calls = installNetwork({ saved: { config: {}, secrets: { api_key: K_SAVED } } });
  const body = await post({ api_key: "***", base_url: "https://api.openai.com" });
  assert.equal(body.status, "error", "https://api.openai.com is not the saved default https://api.openai.com/v1");
  assert.equal(vendorCalls(calls).length, 0);
});

test("an unsafe base URL never reaches the network", async () => {
  reset();
  globalThis.__dns = { "rebind.example.com": "127.0.0.1" };
  const calls = installNetwork({});
  for (const base_url of ["http://api.example.com", "https://localhost", "https://169.254.169.254", "https://phantom-agent", "https://rebind.example.com", "https://user:pw@api.example.com"]) {
    const body = await post({ api_key: K_TYPED, base_url });
    assert.equal(body.status, "error", base_url);
    assert.ok(!JSON.stringify(body).includes(K_TYPED));
  }
  assert.equal(vendorCalls(calls).length, 0);
});

test("the MCP host named in MCP_URL is refused as a base URL", async () => {
  reset();
  const saved = process.env.MCP_URL;
  process.env.MCP_URL = "https://mcp.corp.example/api/v1/stream/mcp";
  try {
    const calls = installNetwork({});
    const body = await post({ api_key: K_TYPED, base_url: "https://mcp.corp.example" });
    assert.equal(body.status, "error");
    assert.equal(vendorCalls(calls).length, 0);
  } finally {
    process.env.MCP_URL = saved;
  }
});

test("each test writes one provider_test audit row with {provider, ok, status} and never the key", async () => {
  reset();
  installNetwork({ saved: { config: {}, secrets: { api_key: K_SAVED } } });
  await post({ api_key: "***" });
  installNetwork({ vendor: () => new Response(JSON.stringify({ error: { type: "authentication_error", message: "bad" } }), { status: 401, headers: { "content-type": "application/json" } }) });
  await post({ api_key: K_TYPED });
  const rows = auditRows();
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], { action: "provider_test", target: "provider:openai", status: "success", metadata: { provider: "openai", ok: true, status: 200 } });
  assert.deepEqual(rows[1], { action: "provider_test", target: "provider:openai", status: "failure", metadata: { provider: "openai", ok: false, status: 401 } });
  const text = JSON.stringify(rows);
  assert.ok(!text.includes(K_SAVED) && !text.includes(K_TYPED));
});

test("a failing audit write never changes the answer", async () => {
  reset();
  installNetwork({ saved: { config: {}, secrets: { api_key: K_SAVED } } });
  const original = globalThis.__audits.push;
  globalThis.__audits.push = () => { throw new Error("audit down"); };
  try {
    const body = await post({ api_key: "***" });
    assert.equal(body.status, "success");
  } finally {
    globalThis.__audits.push = original;
  }
});

test("a body that is not JSON, or not an object, is an error answer, not a 500", async () => {
  reset();
  installNetwork({});
  assert.equal((await post("{nope")).status, "error");
  assert.equal((await post("[1]")).status, "error");
  assert.equal((await post('"x"')).status, "error");
});

for (const { name, fn } of queue) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 8).join("\n     ")); }
}
if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall provider test-route tests passed");
