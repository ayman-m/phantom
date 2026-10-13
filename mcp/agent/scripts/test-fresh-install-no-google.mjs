#!/usr/bin/env node
/**
 * Fresh installs without Google credentials: a Claude-only and an OpenAI-only
 * install boot their runtime config, list models, resolve a model for a turn
 * and dispatch a call without touching, or depending on, any Google credential
 * or host.
 *
 * The real runtime config (including its Vertex credential reader), the real
 * model-registry wiring and the real resolution chain run against a fake
 * network. The fake network answers only the install's own MCP and the one
 * vendor under test; a request to any Google host fails the test. The
 * environment is scrubbed of every Google credential variable first.
 *
 * The install default is the manifest's own default, `vertex/gemini-3.1-pro-preview`,
 * because that is what a fresh Claude-only or OpenAI-only install actually
 * carries until the operator picks another: it names a provider with no
 * credentials, so it must be treated as unset and the first configured
 * provider's recommended model must serve.
 *
 *   node scripts/test-fresh-install-no-google.mjs   (npm run test:fresh-install-no-google)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the code).
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as nodeModule from "node:module";

if (!process.features.typescript || typeof nodeModule.stripTypeScriptTypes !== "function" || typeof nodeModule.registerHooks !== "function") {
  console.log("skip: this Node lacks type stripping or module hooks");
  process.exit(0);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dataModule = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

// The settings read and the audit write go through the MCP proxy; stubbing it
// keeps the test off Next's request machinery. Everything else is real.
const STUBS = {
  "next/server": dataModule(`export const NextResponse = { json(body, init) { return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } }); } };`),
  "@/lib/mcp-proxy": dataModule(`export async function callMcpServer(path, init) { if (path === '/api/v1/settings') return { effective: globalThis.__settings ?? {} }; return {}; }`),
  "node:dns/promises": dataModule(`export async function lookup() { return [{ address: '203.0.113.10', family: 4 }]; }`),
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

// A fresh install has no Google credential anywhere in its environment.
for (const name of Object.keys(process.env)) {
  if (/^(GEMINI_|GOOGLE_|GCLOUD_|CLOUDSDK_)/.test(name)) delete process.env[name];
}
process.env.MCP_TOKEN = "tok-fake";
process.env.MCP_URL = "http://localhost:8080/api/v1/stream/mcp";

const { getEffectiveRuntimeConfig } = await import("../lib/runtime-config.ts");
const creds = await import("../lib/providers/credentials.ts");
const vertexCreds = await import("../lib/vertex-credentials.ts");
const registry = await import("../lib/providers/registry/registry.ts");
const server = await import("../lib/model-registry-server.ts");
const resolution = await import("../lib/providers/model-resolution.ts");
const dispatch = await import("../lib/providers/dispatch.ts");
const modelsRoute = await import("../app/api/agent/models/route.ts");

const queue = [];
const test = (name, fn) => queue.push({ name, fn });
let failed = 0;

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const K_ANT = ["sk", "ant", "api03", "FAKE".repeat(5)].join("-");
const K_OAI = ["sk", "proj-" + "FAKE".repeat(5)].join("-");

const GOOGLE_HOST = /(^|\.)(googleapis\.com|google\.com|google\.internal|gstatic\.com)$/;

/** The install's MCP store plus the vendor API under test. Any Google host throws. */
function installNetwork({ store = {}, vendors = {} } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    calls.push({ url: String(url), host: u.host, init });
    if (GOOGLE_HOST.test(u.hostname)) throw new Error(`a Google host was contacted: ${u.hostname}`);
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    if (u.host === "localhost:8080") {
      if (u.pathname === "/api/v1/providers") {
        const pid = u.searchParams.get("provider_id");
        return json({ instances: store[pid] ? [{ id: `${pid}-1`, provider_id: pid }] : [] });
      }
      const m = u.pathname.match(/^\/api\/v1\/providers\/(.+)-1$/);
      if (m) return json({ instance: { id: `${m[1]}-1`, provider_id: m[1], ...store[m[1]] } });
      return json({ instances: [] });
    }
    if (u.host === "api.anthropic.com") return vendors.anthropic ? json(vendors.anthropic) : json({ error: { message: "no" } }, 401);
    if (u.host === "api.openai.com") return vendors.openai ? json(vendors.openai) : json({ error: { message: "no" } }, 401);
    throw new Error(`unexpected request to ${u.host}`);
  };
  return calls;
}

function reset() {
  creds.bustProviderCredsCache();
  vertexCreds.bustVertexCredsCache?.();
  registry.bustModelRegistryCache();
  server.bustInstallDefaultModelCache();
  // What a fresh install's settings store reports: the manifest default.
  globalThis.__settings = { defaultModel: "vertex/gemini-3.1-pro-preview" };
}

const ANTHROPIC_LIVE = {
  data: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"].map((id) => ({ id, display_name: id, max_input_tokens: 1_000_000, max_tokens: 128_000 })),
  has_more: false,
};
const OPENAI_LIVE = { object: "list", data: ["gpt-6-sol", "gpt-6-luna"].map((id) => ({ id, object: "model" })) };

const INSTALLS = [
  {
    name: "Claude-only",
    provider: "anthropic",
    derived: "anthropic/claude-sonnet-5-5",
    other: "openai",
    otherModel: "gpt-6-sol",
    network: () => installNetwork({ store: { anthropic: { config: {}, secrets: { api_key: K_ANT } } }, vendors: { anthropic: ANTHROPIC_LIVE } }),
    key: K_ANT,
  },
  {
    name: "OpenAI-only",
    provider: "openai",
    derived: "openai/gpt-6-sol",
    other: "anthropic",
    otherModel: "claude-sonnet-5-5",
    network: () => installNetwork({ store: { openai: { config: {}, secrets: { api_key: K_OAI } } }, vendors: { openai: OPENAI_LIVE } }),
    key: K_OAI,
  },
];

for (const install of INSTALLS) {
  const googleCalls = (calls) => calls.filter((c) => GOOGLE_HOST.test(c.host.split(":")[0]));

  test(`${install.name}: the runtime config boots with no Google credential and no error`, async () => {
    reset();
    install.network();
    const cfg = await getEffectiveRuntimeConfig();
    assert.equal(cfg.GOOGLE_APPLICATION_CREDENTIALS, "");
    assert.equal(cfg.GEMINI_API_KEY, "");
  });

  test(`${install.name}: the model list is served, the vendor's models are selectable, Google is never contacted`, async () => {
    reset();
    const calls = install.network();
    const res = await modelsRoute.GET(new Request("http://localhost/api/agent/models"));
    assert.equal(res.status, 200);
    const body = await res.json();
    const mine = body.filter((m) => m.provider === install.provider && m.kind === "chat");
    assert.ok(mine.length > 0 && mine.some((m) => m.selectable), "the configured provider has selectable chat models");
    const vertex = body.filter((m) => m.provider === "vertex");
    assert.ok(vertex.length > 0, "the Gemini models are still listed");
    assert.ok(vertex.every((m) => m.availability === "not_configured" && m.selectable === false), "but none can be chosen");
    assert.deepEqual(googleCalls(calls), []);
    assert.deepEqual(body.filter((m) => m.isDefault).map((m) => [m.ref, m.defaultSource]), [[install.derived, "derived"]]);
    assert.ok(!JSON.stringify(body).includes(install.key), "the key is never served");
  });

  test(`${install.name}: a turn with nothing chosen runs on the vendor's recommended model, though the manifest default names Vertex`, async () => {
    reset();
    const calls = install.network();
    const { result, installDefault } = await server.resolveModelForRequest({});
    assert.equal(installDefault, "vertex/gemini-3.1-pro-preview", "the fresh-install default is the manifest's Vertex ref");
    assert.equal(result.ok, true);
    assert.equal(result.canonical, install.derived);
    assert.equal(result.source, "derived");
    assert.deepEqual(googleCalls(calls), []);
  });

  test(`${install.name}: no stored default at all resolves the same way`, async () => {
    reset();
    globalThis.__settings = {};
    install.network();
    const { result } = await server.resolveModelForRequest({});
    assert.equal(result.ok, true);
    assert.equal(result.canonical, install.derived);
  });

  test(`${install.name}: naming a Gemini model fails loudly and is not swapped for another`, async () => {
    reset();
    const calls = install.network();
    const { result } = await server.resolveModelForRequest({ header: "vertex/gemini-3.1-pro-preview" });
    assert.equal(result.ok, false);
    assert.equal(result.code, "MODEL_UNAVAILABLE");
    assert.equal(result.reason, "PROVIDER_NOT_CONFIGURED");
    assert.equal(result.source, "header");
    assert.ok(result.suggestions.includes(install.derived), "it suggests what can run");
    assert.deepEqual(googleCalls(calls), []);
    // A bare Gemini id behaves the same, and so does a session preference.
    const bare = await server.resolveModelForRequest({ header: "gemini-3.1-pro-preview" });
    assert.equal(bare.result.ok, false);
    const session = await server.resolveModelForRequest({ session: "vertex/gemini-3.7-flash" });
    assert.equal(session.result.ok, false);
    assert.equal(session.result.source, "session");
  });

  test(`${install.name}: the other vendor's models are rejected as not configured, not swapped`, async () => {
    reset();
    install.network();
    const { result } = await server.resolveModelForRequest({ header: `${install.other}/${install.otherModel}` });
    assert.equal(result.ok, false);
    assert.equal(result.reason, "PROVIDER_NOT_CONFIGURED");
  });

  test(`${install.name}: /model accepts the vendor's model and refuses a Gemini one`, async () => {
    reset();
    install.network();
    const entries = await server.loadRegistryEntries();
    const ok = resolution.interpretModelCommand(install.derived.split("/")[1], entries);
    assert.deepEqual(ok, { kind: "set", canonical: install.derived });
    const no = resolution.interpretModelCommand("vertex/gemini-3.1-pro-preview", entries);
    assert.equal(no.kind, "reject");
  });

  test(`${install.name}: the settings proxy accepts the vendor's model as the default and refuses a Gemini one`, async () => {
    reset();
    install.network();
    const entries = await server.loadRegistryEntries();
    const good = resolution.validateModelWrite("settings", { updates: { defaultModel: install.derived.split("/")[1] } }, entries);
    assert.equal(good.ok, true);
    assert.equal(good.body.updates.defaultModel, install.derived, "stored canonical");
    const bad = resolution.validateModelWrite("settings", { updates: { defaultModel: "vertex/gemini-3.1-pro-preview" } }, entries);
    assert.equal(bad.ok, false);
    assert.equal(bad.status, 400);
  });

  test(`${install.name}: dispatch hands the vendor its own stored credentials and never the Google set`, async () => {
    reset();
    install.network();
    const seen = [];
    const spy = (id) => ({
      id,
      capabilities: {},
      async call(req, ctx) {
        seen.push({ id, creds: ctx.creds });
        return { provider: id, model: req.ref.model, text: ["ok"], thinking: [], toolCalls: [], finish: "stop", usage: null, leakedToolCallSuspected: false, raw: null };
      },
    });
    const GOOGLE_MARKER = "google-credential-marker";
    const turn = await dispatch.callModel(
      { ref: { provider: install.provider, model: install.derived.split("/")[1] }, system: "s", messages: [{ role: "user", text: "hi" }], tools: [], toolChoice: "auto", thinking: false, purpose: "chat" },
      // What the chat route passes: the Google credential set from the runtime config.
      { creds: { apiKey: GOOGLE_MARKER, serviceAccountJson: GOOGLE_MARKER } },
      { adapters: { [install.provider]: spy(install.provider) } },
    );
    assert.equal(turn.text[0], "ok");
    assert.equal(seen.length, 1);
    assert.equal(seen[0].creds.apiKey, install.key);
    assert.ok(!JSON.stringify(seen[0].creds).includes(GOOGLE_MARKER), "the Google credential set never reaches another vendor");
  });
}

test("a provider with no stored credentials fails through PROVIDER_NOT_CONFIGURED, never to a Google fallback", async () => {
  reset();
  const calls = installNetwork();
  await assert.rejects(
    dispatch.callModel(
      { ref: { provider: "anthropic", model: "claude-sonnet-5-5" }, system: "s", messages: [{ role: "user", text: "hi" }], tools: [], toolChoice: "auto", thinking: false, purpose: "chat" },
      { creds: {} },
    ),
    (e) => e.code === "PROVIDER_NOT_CONFIGURED",
  );
  assert.deepEqual(calls.filter((c) => GOOGLE_HOST.test(c.host.split(":")[0])), []);
});

test("nothing outside the Vertex adapter reads a Google credential from the environment", () => {
  // The resolution chain, the dispatcher, the credential reader and the two
  // other vendors' adapters take credentials as arguments. The registry only
  // receives the Gemini credentials as a parameter (never from the environment).
  const files = ["lib/providers/model-resolution.ts", "lib/providers/dispatch.ts", "lib/providers/credentials.ts", "lib/providers/connection-test.ts", "lib/providers/streaming-call.ts"];
  const walk = (dir) => readdirSync(dir).flatMap((n) => {
    const full = join(dir, n);
    return statSync(full).isDirectory() ? walk(full) : /\.ts$/.test(n) ? [full] : [];
  });
  for (const dir of ["lib/providers/anthropic", "lib/providers/openai", "lib/providers/registry"]) {
    files.push(...walk(join(root, dir)).map((f) => relative(root, f)));
  }
  const hits = [];
  for (const rel of files) {
    readFileSync(join(root, rel), "utf8").split("\n").forEach((line, i) => {
      if (/process\.env\.(GEMINI|GOOGLE)|process\.env\[/.test(line)) hits.push(`${rel}:${i + 1}`);
    });
  }
  assert.deepEqual(hits, []);
});

test("the manifest does not require a Vertex provider", () => {
  const manifest = readFileSync(join(root, "..", "..", "bundles", "spark", "manifest.yaml"), "utf8");
  const block = manifest.slice(manifest.indexOf("\nproviders:\n"));
  for (const id of ["vertex", "anthropic", "openai"]) {
    const m = block.match(new RegExp(`- id: "${id}"[\\s\\S]*?required: (true|false)`));
    assert.ok(m, `provider ${id} is declared`);
    assert.equal(m[1], "false", `${id} is optional`);
  }
});

for (const { name, fn } of queue) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}
if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall tests passed");
