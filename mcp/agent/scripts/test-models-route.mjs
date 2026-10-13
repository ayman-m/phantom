#!/usr/bin/env node
/**
 * GET /api/agent/models: runs the real route handler (and the server wiring
 * behind it) against stubbed Next, runtime-config, MCP-proxy and DNS modules
 * and a fake network, and asserts the served shape; plus the endpoint audit:
 * no second model list may exist outside the registry catalogs.
 *
 *   node scripts/test-models-route.mjs   (npm run test:models-route)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the route).
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

const STUBS = {
  "next/server": dataModule(`export const NextResponse = { json(body, init) { return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } }); } };`),
  "@/lib/runtime-config": dataModule(`export async function getEffectiveRuntimeConfig() { return globalThis.__runtime; }`),
  "@/lib/mcp-proxy": dataModule(`export async function callMcpServer(path, init) { globalThis.__audits.push({ path, init }); if (path === '/api/v1/settings') return { effective: globalThis.__settings ?? {} }; return {}; }`),
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

globalThis.__audits = [];
globalThis.__runtime = {};
process.env.MCP_TOKEN = "tok-fake";
process.env.MCP_URL = "http://localhost:8080/api/v1/stream/mcp";

const route = await import("../app/api/agent/models/route.ts");
const creds = await import("../lib/providers/credentials.ts");
const registry = await import("../lib/providers/registry/registry.ts");
const server = await import("../lib/model-registry-server.ts");

let failed = 0;
const queue = [];
const test = (name, fn) => queue.push({ name, fn });

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const K_ANT = ["sk", "ant", "api03", "FAKE".repeat(5)].join("-");
const K_OAI = ["sk", "proj-" + "FAKE".repeat(5)].join("-");
const K_GEM = ["AI", "zaSy", "FAKE".repeat(8)].join("");
const SA = '{"type":"service_account","private_key":"fake"}';

/** A fake network: the MCP provider store plus the three vendor APIs. */
function installNetwork({ store = {}, vendors = {} } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    calls.push({ url: String(url), init });
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    if (u.host === "localhost:8080") {
      if (u.pathname === "/api/v1/providers") {
        const pid = u.searchParams.get("provider_id");
        return json({ instances: store[pid] ? [{ id: `${pid}-1`, provider_id: pid }] : [] });
      }
      const m = u.pathname.match(/^\/api\/v1\/providers\/(.+)-1$/);
      return json({ instance: { id: `${m[1]}-1`, provider_id: m[1], ...store[m[1]] } });
    }
    if (u.host === "api.anthropic.com") return vendors.anthropic ? json(vendors.anthropic) : json({ error: { message: "no" } }, 401);
    if (u.host === "api.openai.com") return vendors.openai ? json(vendors.openai) : json({ error: { message: "no" } }, 401);
    if (u.host === "generativelanguage.googleapis.com") return vendors.gemini ? json(vendors.gemini) : json({ error: { message: "no" } }, 403);
    throw new Error(`unexpected request to ${u.host}`);
  };
  return calls;
}

function reset() {
  creds.bustProviderCredsCache();
  registry.bustModelRegistryCache();
  server.bustInstallDefaultModelCache();
  globalThis.__audits = [];
  globalThis.__settings = { defaultModel: "vertex/gemini-3.1-pro-preview" };
}

const get = async (query = "") => {
  const res = await route.GET(new Request(`http://localhost/api/agent/models${query}`));
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /json/);
  return await res.json();
};

const ANTHROPIC_LIVE = { data: ["claude-opus-5-5", "claude-sonnet-5-5"].map((id) => ({ id, display_name: id, max_input_tokens: 1_000_000, max_tokens: 128_000, lifecycle: "active" })), has_more: false };

test("the route exports only its handler and delegates to the server wiring", () => {
  const src = readFileSync(join(root, "app/api/agent/models/route.ts"), "utf8");
  const exports = [...src.matchAll(/^export\s+(?:async\s+)?(?:const|function)\s+(\w+)/gm)].map((m) => m[1]).sort();
  assert.deepEqual(exports, ["GET", "dynamic"]);
  assert.match(src, /listModelsForApi/);
  assert.ok(!/VERTEX_MODELS|ANTHROPIC_MODELS|wip/.test(src));
});

test("a Gemini-only install: a bare array with the legacy fields and the registry's", async () => {
  reset();
  globalThis.__runtime = { GEMINI_API_KEY: K_GEM, GOOGLE_APPLICATION_CREDENTIALS: "" };
  const calls = installNetwork({ vendors: { gemini: { models: [{ name: "models/gemini-3.1-pro-preview", inputTokenLimit: 1_048_576, outputTokenLimit: 65_536 }] } } });
  const body = await get();
  assert.ok(Array.isArray(body));
  const vertex = body.filter((m) => m.provider === "vertex");
  const chat = vertex.filter((m) => m.kind === "chat").map((m) => m.model).sort();
  assert.deepEqual(chat, ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3.0-pro", "gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash"]);
  assert.deepEqual(vertex.filter((m) => m.kind !== "chat").map((m) => `${m.kind}:${m.model}`).sort(), [
    "embedding:gemini-embedding-001", "embedding:text-embedding-005", "image:imagen-3.0-generate-002", "image:imagen-4.0-generate-preview", "voice:chirp-3-hd",
  ]);
  const pro = body.find((m) => m.ref === "vertex/gemini-3.1-pro-preview");
  assert.deepEqual(Object.keys(pro).sort(), [
    "availability", "contextWindow", "defaultSource", "displayName", "forcedToolChoice", "interactionPatterns", "isDefault", "kind", "launchStage",
    "lifecycle", "liveSeenAt", "maxInput", "maxOutput", "model", "pricing", "pricingNote", "pricingValidUntil", "pricingVerified", "priced",
    "provider", "providerState", "recommended", "ref", "reason", "refreshError", "selectable", "source", "supportsThinking", "supportsTools",
    "thinking", "tokenizerFactor", "unverified",
  ].sort());
  assert.equal(pro.provider, "vertex");
  assert.equal(pro.contextWindow, 1_048_576, "live value wins");
  assert.equal(pro.supportsThinking, true);
  assert.equal(pro.supportsTools, true);
  assert.equal(pro.launchStage, "PUBLIC_PREVIEW");
  assert.deepEqual(pro.interactionPatterns, ["streaming_api"]);
  assert.equal(pro.availability, "available");
  assert.equal(pro.selectable, true);
  assert.equal(pro.source, "live+curated");
  assert.ok(pro.liveSeenAt);
  assert.equal(pro.isDefault, true);
  assert.equal(pro.defaultSource, "default");
  assert.equal(body.filter((m) => m.isDefault).length, 1);
  assert.ok(body.filter((m) => !m.isDefault).every((m) => m.defaultSource === null));
  assert.deepEqual(pro.pricing, { inputPerM: 2.5, outputPerM: 12, cacheReadPerM: 0.625 });
  assert.equal(pro.priced, true);
  assert.equal(body.find((m) => m.model === "imagen-3.0-generate-002").interactionPatterns[0], "async_job");
  assert.equal(body.find((m) => m.model === "gemini-2.5-flash-lite").supportsThinking, false);
  assert.equal(body.find((m) => m.model === "gemini-2.5-pro").launchStage, "DEPRECATED");
  assert.equal(body.find((m) => m.model === "gemini-2.5-pro").availability, "deprecated");
  assert.equal(body.find((m) => m.model === "gemini-2.5-pro").selectable, true);
  assert.equal(body.find((m) => m.model === "gemini-3.7-flash").priced, false);
  assert.equal(body.filter((m) => m.provider !== "vertex").every((m) => m.availability === "not_configured" && !m.selectable), true);
  assert.ok(!calls.some((c) => c.url.includes("api.anthropic.com") || c.url.includes("api.openai.com")), "unconfigured providers are not contacted");
  assert.ok(!JSON.stringify(body).includes(K_GEM));
});

test("the default is the install's defaultModel setting, read from the MCP settings store", async () => {
  reset();
  globalThis.__runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA };
  globalThis.__settings = { defaultModel: "vertex/gemini-3.7-flash" };
  installNetwork();
  const body = await get();
  assert.deepEqual(body.filter((m) => m.isDefault).map((m) => m.ref), ["vertex/gemini-3.7-flash"]);
  assert.equal(body.find((m) => m.isDefault).defaultSource, "default");
});

test("no usable setting: the default is derived from the first configured provider's recommended model", async () => {
  reset();
  globalThis.__runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA };
  globalThis.__settings = {};
  installNetwork();
  const body = await get();
  const def = body.filter((m) => m.isDefault);
  assert.deepEqual(def.map((m) => m.ref), ["vertex/gemini-3.1-pro-preview"]);
  assert.equal(def[0].defaultSource, "derived");
});

test("a default whose provider has no credentials is derived, not served", async () => {
  reset();
  globalThis.__runtime = {};
  globalThis.__settings = { defaultModel: "anthropic/claude-opus-5-5" };
  installNetwork();
  const body = await get();
  // Nothing is configured, so nothing can be the default.
  assert.equal(body.filter((m) => m.isDefault).length, 0);
});

test("the default is read through a 30 s cache that the settings write drops", async () => {
  reset();
  globalThis.__runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA };
  installNetwork();
  assert.equal((await get()).find((m) => m.isDefault).ref, "vertex/gemini-3.1-pro-preview");
  globalThis.__settings = { defaultModel: "vertex/gemini-3.7-flash" };
  assert.equal((await get()).find((m) => m.isDefault).ref, "vertex/gemini-3.1-pro-preview", "cached");
  server.bustInstallDefaultModelCache();
  assert.equal((await get()).find((m) => m.isDefault).ref, "vertex/gemini-3.7-flash");
});

test("a service-account-only install lists Gemini as unverified and selectable without any provider call", async () => {
  reset();
  globalThis.__runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA };
  const calls = installNetwork();
  const body = await get();
  const e = body.find((m) => m.ref === "vertex/gemini-3.1-pro-preview");
  assert.equal(e.availability, "unverified");
  assert.equal(e.selectable, true);
  assert.equal(e.providerState, "unchecked");
  assert.deepEqual(calls.filter((c) => !c.url.includes("localhost:8080")), []);
});

test("an install with no credentials lists every model as not configured, none selectable", async () => {
  reset();
  globalThis.__runtime = {};
  installNetwork();
  const body = await get();
  assert.ok(body.length > 20);
  assert.ok(body.every((m) => m.availability === "not_configured" && m.selectable === false));
  assert.equal(body.filter((m) => m.selectable).length, 0);
});

test("a stored Anthropic key lists Claude from the live list, and chat can run on it", async () => {
  reset();
  globalThis.__runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA };
  const calls = installNetwork({
    store: { anthropic: { config: {}, secrets: { api_key: K_ANT } } },
    vendors: { anthropic: ANTHROPIC_LIVE },
  });
  const body = await get();
  const opus = body.find((m) => m.ref === "anthropic/claude-opus-5-5");
  assert.equal(opus.availability, "available");
  assert.equal(opus.source, "live+curated");
  assert.equal(opus.selectable, true);
  assert.ok(!opus.reason, "no reason is given for a selectable model");
  assert.equal(opus.tokenizerFactor, 1.3);
  assert.equal(opus.pricing.inputPerM, 4);
  assert.equal(opus.pricingVerified, "2026-10-13");
  const missing = body.find((m) => m.ref === "anthropic/claude-haiku-5-5");
  assert.equal(missing.availability, "unavailable");
  const anthropicCall = calls.find((c) => c.url.includes("api.anthropic.com"));
  assert.equal(anthropicCall.init.headers.Authorization, `Bearer ${K_ANT}`);
  assert.ok(!JSON.stringify(body).includes(K_ANT));
  const storeCall = calls.find((c) => c.url.includes("include_secrets=true"));
  assert.ok(storeCall, "credentials come from the ProviderStore over loopback");
});

test("each live refresh writes an audit row through the MCP", async () => {
  reset();
  globalThis.__runtime = {};
  installNetwork({ store: { anthropic: { config: {}, secrets: { api_key: K_ANT } } }, vendors: { anthropic: ANTHROPIC_LIVE } });
  await get();
  await new Promise((r) => setImmediate(r));
  const rows = globalThis.__audits.filter((a) => a.path === "/api/v1/audit").map((a) => a.init.body);
  const refreshed = rows.filter((r) => r.action === "provider_models_refreshed");
  assert.equal(refreshed.length, 1);
  assert.equal(refreshed[0].metadata.provider, "anthropic");
  assert.equal(refreshed[0].metadata.model_count, 2);
  assert.equal(refreshed[0].status, "success");
  assert.ok(!JSON.stringify(rows).includes(K_ANT));
});

test("a provider that is down does not break the list; the failure is audited", async () => {
  reset();
  globalThis.__runtime = {};
  installNetwork({ store: { openai: { config: {}, secrets: { api_key: K_OAI } } } });
  const body = await get();
  const gpt = body.find((m) => m.ref === "openai/gpt-6-sol");
  assert.equal(gpt.providerState, "offline");
  assert.equal(gpt.availability, "unverified");
  assert.equal(gpt.selectable, false);
  assert.match(gpt.refreshError, /HTTP 401/);
  await new Promise((r) => setImmediate(r));
  const failures = globalThis.__audits.filter((a) => a.path === "/api/v1/audit").map((a) => a.init.body).filter((r) => r.action === "provider_models_refresh_failed");
  assert.equal(failures.length, 1);
  assert.equal(failures[0].metadata.error_kind, "auth");
});

test("an OpenAI-only install: the served list has the curated models selectable and a live-only chat id unverified and not selectable", async () => {
  reset();
  globalThis.__runtime = {};
  const ids = ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-9-future", "text-embedding-3-large"];
  installNetwork({
    store: { openai: { config: { organization: "org-abc123" }, secrets: { api_key: K_OAI } } },
    vendors: { openai: { object: "list", data: ids.map((id) => ({ id, object: "model" })) } },
  });
  const body = await get();
  const openai = body.filter((m) => m.provider === "openai");
  const sol = openai.find((m) => m.ref === "openai/gpt-6-sol");
  assert.equal(sol.selectable, true, "chat can run on the curated model the key sees");
  assert.equal(sol.availability, "available");
  assert.equal(sol.providerState, "live");
  assert.equal(sol.recommended, true);
  assert.equal(sol.priced, true);
  for (const id of ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-sol"]) {
    assert.equal(openai.find((m) => m.model === id).selectable, true, id);
  }
  const unseen = openai.find((m) => m.model === "gpt-5.6-terra");
  assert.equal(unseen.selectable, false, "a curated model the key cannot see");
  assert.equal(unseen.availability, "unavailable");
  const extra = openai.find((m) => m.model === "gpt-9-future");
  assert.equal(extra.availability, "unverified");
  assert.equal(extra.selectable, false);
  assert.equal(extra.source, "live");
  assert.ok(!openai.some((m) => m.model === "text-embedding-3-large"), "a non-chat id is not listed");
  // Nothing Google is configured, so the default is derived from the first configured provider.
  const def = body.filter((m) => m.isDefault);
  assert.deepEqual(def.map((m) => [m.ref, m.defaultSource]), [["openai/gpt-6-sol", "derived"]]);
  assert.ok(!JSON.stringify(body).includes(K_OAI));
});

test("the registry cache is dropped when credentials change", async () => {
  reset();
  globalThis.__runtime = {};
  const calls = installNetwork({ store: { anthropic: { config: {}, secrets: { api_key: K_ANT } } }, vendors: { anthropic: ANTHROPIC_LIVE } });
  await get();
  await get();
  assert.equal(calls.filter((c) => c.url.includes("api.anthropic.com")).length, 1);
  creds.bustProviderCredsCache("anthropic");
  registry.bustModelRegistryCache("anthropic");
  await get();
  assert.equal(calls.filter((c) => c.url.includes("api.anthropic.com")).length, 2);
});

/* ─── Endpoint audit ────────────────────────────────────────── */

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.(ts|tsx)$/.test(name)) yield full;
  }
}

test("no second model list: model ids appear only in the registry catalogs and the docs", () => {
  const allowed = (rel) =>
    rel.startsWith("lib/providers/registry/catalog-") ||
    rel.startsWith("app/help/") ||
    rel === "lib/journeys.ts" ||
    rel === "lib/release-notes.ts" ||
    rel === "lib/api-catalog.ts";
  const hits = [];
  for (const dir of ["app", "lib", "components"]) {
    for (const file of walk(join(root, dir))) {
      const rel = relative(root, file);
      if (allowed(rel)) continue;
      readFileSync(file, "utf8").split("\n").forEach((line, i) => {
        if (/gemini-2\.5-pro/.test(line)) hits.push(`${rel}:${i + 1}`);
      });
    }
  }
  assert.deepEqual(hits, []);
});

test("the retired tables and patterns are gone from the sources", () => {
  const forbidden = ["VERTEX_MODELS", "ANTHROPIC_MODELS", "MODEL_CAP", "PREFIX_CAPS", "MODEL_PRICING_TABLE", "FALLBACK_PRICING", "openai-codex", "cli_tool", "interactive_session"];
  const hits = [];
  for (const dir of ["app", "lib", "components"]) {
    for (const file of walk(join(root, dir))) {
      const rel = relative(root, file);
      if (rel.startsWith("app/help/") || rel === "lib/journeys.ts") continue;
      readFileSync(file, "utf8").split("\n").forEach((line, i) => {
        for (const term of forbidden) if (line.includes(term)) hits.push(`${rel}:${i + 1} ${term}`);
      });
    }
  }
  assert.deepEqual(hits, []);
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
