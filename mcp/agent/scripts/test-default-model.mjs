#!/usr/bin/env node
/**
 * One canonical default model, and loud validation.
 *
 * Covers lib/providers/model-resolution.ts (the resolution chain header ->
 * session -> install default -> derived default, every failure, the `/model`
 * command, the write-time validators) and the server wiring behind it: the
 * install default read from the MCP settings store with its 30 s cache, the
 * settings and jobs proxies that refuse a model the registry does not accept,
 * and source-level guards that GEMINI_MODEL and the old resolver are gone.
 *
 *   node scripts/test-default-model.mjs   (npm run test:default-model)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the modules).
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
  "next/server": dataModule(`
    export class NextResponse extends Response {
      static json(body, init) {
        return new NextResponse(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } });
      }
    }`),
  "@/lib/runtime-config": dataModule(`
    export async function getEffectiveRuntimeConfig() { return globalThis.__runtime; }
    export function deriveMcpBaseUrl(u) { const x = new URL(u); return x.protocol + '//' + x.host; }`),
  "@/lib/mcp-proxy": dataModule(`
    import { NextResponse } from 'next/server';
    export async function callMcpServer(path, init) {
      globalThis.__mcp.push({ path, init });
      if (path === '/api/v1/settings') { globalThis.__settingsReads += 1; return { effective: globalThis.__settings ?? {} }; }
      return {};
    }
    export async function proxyToMcp(request, path, options = {}) {
      const body = options.body !== undefined ? options.body : await request.text();
      globalThis.__proxied.push({ path, method: options.method ?? request.method, body });
      return new NextResponse(JSON.stringify({ ok: true }), { status: 200 });
    }`),
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

globalThis.__mcp = [];
globalThis.__proxied = [];
globalThis.__settings = {};
globalThis.__settingsReads = 0;
globalThis.__runtime = {};
process.env.MCP_TOKEN = "tok-fake";
process.env.MCP_URL = "http://localhost:8080/api/v1/stream/mcp";

const R = await import("../lib/providers/model-resolution.ts");
const reg = await import("../lib/providers/registry/registry.ts");
const { CURATED_CATALOG } = await import("../lib/providers/registry/lookup.ts");
const server = await import("../lib/model-registry-server.ts");
const settingsRoute = await import("../app/api/agent/settings/route.ts");
const jobsRoute = await import("../app/api/agent/jobs/route.ts");
const jobRoute = await import("../app/api/agent/jobs/[jobName]/route.ts");

let failed = 0;
const queue = [];
const test = (name, fn) => queue.push({ name, fn });

/* ─── Registry entries for a chosen set of configured providers ─ */

const ALL_PROVIDERS = ["vertex", "anthropic", "openai"];

async function entriesFor(configured, { catalog = CURATED_CATALOG, dispatchable = ALL_PROVIDERS } = {}) {
  const creds = {};
  if (configured.includes("vertex")) creds.vertex = { serviceAccountJson: '{"type":"service_account"}' };
  if (configured.includes("anthropic")) creds.anthropic = { apiKey: "k-a" };
  if (configured.includes("openai")) creds.openai = { apiKey: "k-o" };
  const registry = reg.createModelRegistry({
    publishFacts: false,
    dispatchable,
    catalog,
    // Every curated chat model is "listed" by its provider.
    fetchLive: async (provider) =>
      catalog.filter((m) => m.provider === provider && m.kind === "chat").map((m) => ({ id: m.model })),
  });
  return await registry.list({ creds, includeRetired: true });
}

const withLifecycle = (catalog, ref, lifecycle) =>
  catalog.map((m) => (`${m.provider}/${m.model}` === ref ? { ...m, lifecycle } : m));

const REC = { vertex: "vertex/gemini-3.1-pro-preview", anthropic: "anthropic/claude-sonnet-5-5", openai: "openai/gpt-6-sol" };
const recommendedOf = (entries, provider) => entries.find((e) => e.provider === provider && e.recommended)?.ref;

/* ─── The chain ─────────────────────────────────────────────── */

test("the recommended models are the ones the derivation uses", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  for (const p of ALL_PROVIDERS) assert.ok(recommendedOf(all, p), `${p} has a recommended model`);
  assert.equal(recommendedOf(all, "vertex"), REC.vertex);
});

test("header beats session beats install default; the result carries the canonical ref and its source", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  const input = { header: "anthropic/claude-opus-5-5", session: "openai/gpt-6-sol", installDefault: "vertex/gemini-3.7-flash" };
  let r = R.resolveChatModel(input, all);
  assert.deepEqual([r.ok, r.canonical, r.source, r.ref], [true, "anthropic/claude-opus-5-5", "header", { provider: "anthropic", model: "claude-opus-5-5" }]);
  r = R.resolveChatModel({ ...input, header: undefined }, all);
  assert.deepEqual([r.canonical, r.source], ["openai/gpt-6-sol", "session"]);
  r = R.resolveChatModel({ ...input, header: "", session: "  " }, all);
  assert.deepEqual([r.canonical, r.source], ["vertex/gemini-3.7-flash", "default"]);
});

test("a bare header id is qualified by the request's provider, and 'auto' is ignored", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  assert.equal(R.resolveChatModel({ header: "gemini-3.7-flash", headerProvider: "vertex" }, all).canonical, "vertex/gemini-3.7-flash");
  assert.equal(R.resolveChatModel({ header: "gemini-3.7-flash", headerProvider: "auto" }, all).canonical, "vertex/gemini-3.7-flash");
  // A bare stored id still resolves when exactly one configured provider has it.
  assert.equal(R.resolveChatModel({ session: "claude-haiku-5-5" }, all).canonical, "anthropic/claude-haiku-5-5");
});

test("with no usable default the first configured provider's recommended model serves (vertex, anthropic, openai)", async () => {
  for (const [configured, want] of [
    [["vertex", "anthropic", "openai"], REC.vertex],
    [["anthropic", "openai"], REC.anthropic],
    [["openai"], REC.openai],
    [["openai", "vertex"], REC.vertex],
  ]) {
    const all = await entriesFor(configured);
    for (const installDefault of [undefined, "", "   "]) {
      const r = R.resolveChatModel({ installDefault }, all);
      assert.deepEqual([r.ok, r.canonical, r.source], [true, want, "derived"], configured.join());
    }
  }
});

test("a default whose provider is not configured is treated as unset and the derived model serves", async () => {
  const all = await entriesFor(["anthropic"]);
  const r = R.resolveChatModel({ installDefault: "vertex/gemini-3.1-pro-preview" }, all);
  assert.deepEqual([r.ok, r.canonical, r.source], [true, REC.anthropic, "derived"]);
});

test("an OpenAI-only and a Claude-only install both serve: the manifest's Vertex default is as good as unset", async () => {
  // The settings manifest ships `vertex/gemini-3.1-pro-preview` as the default; with no Google
  // credentials that must fall through to the derived model, not reject the turn.
  for (const [configured, want] of [[["openai"], REC.openai], [["anthropic"], REC.anthropic]]) {
    const all = await entriesFor(configured);
    const r = R.resolveChatModel({ installDefault: "vertex/gemini-3.1-pro-preview" }, all);
    assert.deepEqual([r.ok, r.canonical, r.source], [true, want, "derived"], configured.join());
    assert.equal(r.entry.selectable, true);
    assert.deepEqual(R.describeInstallDefault("vertex/gemini-3.1-pro-preview", all), { ref: want, source: "derived" });
  }
});

test("a configured default serves as itself", async () => {
  const all = await entriesFor(["vertex", "anthropic"]);
  const r = R.resolveChatModel({ installDefault: "anthropic/claude-opus-5-5" }, all);
  assert.deepEqual([r.ok, r.canonical, r.source], [true, "anthropic/claude-opus-5-5", "default"]);
});

test("the derivation looks at the first configured provider only: no hop to another vendor", async () => {
  const catalog = withLifecycle(CURATED_CATALOG, REC.vertex, { stage: "retired", retiresAt: "2026-01-01" });
  const all = await entriesFor(["vertex", "anthropic"], { catalog });
  const r = R.resolveChatModel({}, all);
  assert.equal(r.ok, false);
  assert.equal(r.code, "MODEL_UNAVAILABLE");
  assert.equal(r.source, "derived");
  assert.equal(r.reason, "MODEL_NOT_SELECTABLE");
  assert.ok(r.suggestions.length > 0 && r.suggestions.length <= 3);
  assert.match(r.message, /No default model is set/);
});

test("no provider configured: a clear error that points at the Providers page", async () => {
  const all = await entriesFor([]);
  const r = R.resolveChatModel({ installDefault: "vertex/gemini-3.1-pro-preview" }, all);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "NO_PROVIDER_CONFIGURED");
  assert.match(r.message, /Providers page/);
  assert.deepEqual(r.suggestions, []);
});

test("an unknown, retired or unselectable model FAILS at every link; nothing is substituted", async () => {
  const retiredCatalog = withLifecycle(CURATED_CATALOG, "vertex/gemini-3.7-flash", { stage: "retired", retiresAt: "2026-01-01" });
  const all = await entriesFor(ALL_PROVIDERS, { catalog: retiredCatalog });

  // header
  let r = R.resolveChatModel({ header: "vertex/gemini-9-imaginary", session: "openai/gpt-6-sol", installDefault: REC.vertex }, all);
  assert.deepEqual([r.ok, r.code, r.reason, r.source], [false, "MODEL_UNAVAILABLE", "MODEL_UNKNOWN", "header"]);
  assert.ok(r.suggestions.every((s) => all.find((e) => e.ref === s).selectable));
  assert.match(r.message, /gemini-9-imaginary/);

  // retired
  r = R.resolveChatModel({ header: "vertex/gemini-3.7-flash" }, all);
  assert.deepEqual([r.ok, r.reason, r.source], [false, "MODEL_NOT_SELECTABLE", "header"]);
  assert.match(r.message, /retired/i);

  // session: names /model auto
  r = R.resolveChatModel({ session: "vertex/gemini-3.7-flash", installDefault: REC.vertex }, all);
  assert.deepEqual([r.ok, r.reason, r.source], [false, "MODEL_NOT_SELECTABLE", "session"]);
  assert.match(r.message, /\/model auto/);

  // default: a default that is configured-but-unknown fails; it is not derived around
  r = R.resolveChatModel({ installDefault: "vertex/gemini-3.7-flash" }, all);
  assert.deepEqual([r.ok, r.reason, r.source], [false, "MODEL_NOT_SELECTABLE", "default"]);
  assert.match(r.message, /Models page/);
  r = R.resolveChatModel({ installDefault: "openai/not-a-model" }, all);
  assert.deepEqual([r.ok, r.reason, r.source], [false, "MODEL_UNKNOWN", "default"]);

  // a provider with no credentials
  const vertexOnly = await entriesFor(["vertex"]);
  r = R.resolveChatModel({ header: "openai/gpt-6-sol" }, vertexOnly);
  assert.deepEqual([r.ok, r.reason], [false, "PROVIDER_NOT_CONFIGURED"]);
  assert.match(r.message, /Providers page/);

  // not a chat model
  r = R.resolveChatModel({ header: "vertex/gemini-embedding-001" }, all);
  assert.deepEqual([r.ok, r.reason], [false, "MODEL_NOT_SELECTABLE"]);
});

test("a bare id offered by two configured providers is AMBIGUOUS and lists the qualified refs", async () => {
  const twin = { ...CURATED_CATALOG.find((m) => m.provider === "anthropic" && m.model === "claude-opus-5-5") };
  const catalog = [...CURATED_CATALOG, { ...twin, provider: "vertex" }];
  const all = await entriesFor(["vertex", "anthropic"], { catalog });
  const r = R.resolveChatModel({ header: "claude-opus-5-5" }, all);
  assert.deepEqual([r.ok, r.reason], [false, "AMBIGUOUS"]);
  assert.deepEqual([...r.options].sort(), ["anthropic/claude-opus-5-5", "vertex/claude-opus-5-5"]);
});

test("a provider this build cannot dispatch to is reported with the registry's reason", async () => {
  const all = await entriesFor(ALL_PROVIDERS, { dispatchable: ["vertex"] });
  const r = R.resolveChatModel({ header: "anthropic/claude-opus-5-5" }, all);
  assert.deepEqual([r.ok, r.reason], [false, "MODEL_NOT_SELECTABLE"]);
  assert.match(r.message, /cannot run on Anthropic/);
});

test("describeInstallDefault says which of the two serves, and why none does", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  assert.deepEqual(R.describeInstallDefault("anthropic/claude-opus-5-5", all), { ref: "anthropic/claude-opus-5-5", source: "default" });
  assert.deepEqual(R.describeInstallDefault(undefined, all), { ref: REC.vertex, source: "derived" });
  const none = R.describeInstallDefault("vertex/nope", all);
  assert.equal(none.ref, null);
  assert.equal(none.source, "none");
  assert.match(none.problem, /nope/);
});

/* ─── /model ─────────────────────────────────────────────────── */

test("/model: no argument shows, auto and default clear", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  assert.deepEqual(R.interpretModelCommand("", all), { kind: "show" });
  assert.deepEqual(R.interpretModelCommand("   ", all), { kind: "show" });
  assert.deepEqual(R.interpretModelCommand("auto", all), { kind: "clear" });
  assert.deepEqual(R.interpretModelCommand("DEFAULT", all), { kind: "clear" });
});

test("/model <name> stores the canonical ref, whether the operator typed it qualified or bare", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  assert.deepEqual(R.interpretModelCommand("gemini-3.7-flash", all), { kind: "set", canonical: "vertex/gemini-3.7-flash" });
  assert.deepEqual(R.interpretModelCommand("  anthropic/claude-haiku-5-5 ", all), { kind: "set", canonical: "anthropic/claude-haiku-5-5" });
  assert.deepEqual(R.interpretModelCommand("VERTEX/Gemini-3.7-Flash", all), { kind: "set", canonical: "vertex/gemini-3.7-flash" });
});

test("/model <bad name> stores nothing and returns suggestions", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  const c = R.interpretModelCommand("gemini-3.7-flsh", all);
  assert.equal(c.kind, "reject");
  assert.match(c.message, /^Not changed\./);
  assert.ok(c.suggestions.includes("vertex/gemini-3.7-flash"), c.suggestions.join());
  assert.match(c.message, /vertex\/gemini-3\.7-flash/);
  const unconfigured = R.interpretModelCommand("openai/gpt-6-sol", await entriesFor(["vertex"]));
  assert.equal(unconfigured.kind, "reject");
  assert.match(unconfigured.message, /not configured/);
});

test("/model with no argument reports the session ref, the install default and where each comes from", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  let text = R.renderModelStatus({ session: "anthropic/claude-opus-5-5", installDefault: "vertex/gemini-3.7-flash" }, all);
  assert.match(text, /runs on `anthropic\/claude-opus-5-5` \(this session.s \/model preference\)/);
  assert.match(text, /Session preference: `anthropic\/claude-opus-5-5`/);
  assert.match(text, /Install default: `vertex\/gemini-3\.7-flash` \(set on the Models page\)/);

  text = R.renderModelStatus({ installDefault: "vertex/gemini-3.7-flash" }, all);
  assert.match(text, /runs on `vertex\/gemini-3\.7-flash` \(the install's default\)/);
  assert.match(text, /Session preference: none/);

  text = R.renderModelStatus({ header: "openai/gpt-6-sol", installDefault: "vertex/gemini-3.7-flash" }, all);
  assert.match(text, /\(chosen in the chat header\)/);

  text = R.renderModelStatus({}, await entriesFor(["anthropic"]));
  assert.match(text, /runs on `anthropic\/claude-sonnet-5-5` \(derived/);
  assert.match(text, /Install default: `anthropic\/claude-sonnet-5-5` \(derived/);

  const retired = await entriesFor(ALL_PROVIDERS, { catalog: withLifecycle(CURATED_CATALOG, "vertex/gemini-3.7-flash", { stage: "retired", retiresAt: "2026-01-01" }) });
  text = R.renderModelStatus({ session: "vertex/gemini-3.7-flash" }, retired);
  assert.match(text, /cannot run/);
  assert.match(text, /Session preference: `vertex\/gemini-3\.7-flash`/);
});

/* ─── Validation at the proxies (pure) ───────────────────────── */

test("settings body: defaultModel must resolve and is rewritten canonical; clear and other keys pass", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  let v = R.validateSettingsBody({ updates: { defaultModel: "claude-opus-5-5", defaultLogFormat: "CEF" }, clear: [], actor: "op" }, all);
  assert.deepEqual([v.ok, v.body], [true, { updates: { defaultModel: "anthropic/claude-opus-5-5", defaultLogFormat: "CEF" }, clear: [], actor: "op" }]);

  const untouched = { updates: { defaultLogFormat: "CEF" } };
  assert.equal(R.validateSettingsBody(untouched, all).body, untouched);
  const clearing = { clear: ["defaultModel"] };
  assert.equal(R.validateSettingsBody(clearing, all).body, clearing);
  assert.equal(R.bodyTouchesModel("settings", clearing), false);

  v = R.validateSettingsBody({ updates: { defaultModel: "vertex/gemini-9" } }, all);
  assert.deepEqual([v.ok, v.status, v.body.code, v.body.field], [false, 400, "MODEL_UNKNOWN", "defaultModel"]);
  assert.ok(v.body.suggestions.length > 0);
  assert.match(v.body.error, /Try:/);

  for (const bad of [42, null, "", "  ", ["x"], { a: 1 }, true]) {
    v = R.validateSettingsBody({ updates: { defaultModel: bad } }, all);
    assert.deepEqual([v.ok, v.status, v.body.code], [false, 400, "INVALID_MODEL"], JSON.stringify(bad));
  }
  v = R.validateSettingsBody({ updates: { defaultModel: "openai/gpt-6-sol" } }, await entriesFor(["vertex"]));
  assert.deepEqual([v.ok, v.body.code], [false, "PROVIDER_NOT_CONFIGURED"]);
});

test("job body: '' clears, absent or null changes nothing, anything else must resolve and is stored canonical", async () => {
  const all = await entriesFor(ALL_PROVIDERS);
  for (const body of [{ name: "j" }, { model_id: "" }, { model_id: null }, { cron: "* * * * *" }]) {
    const v = R.validateJobBody(body, all);
    assert.deepEqual([v.ok, v.body], [true, body]);
    assert.equal(R.bodyTouchesModel("job", body), false);
  }
  let v = R.validateJobBody({ name: "j", model_id: "gemini-3.7-flash" }, all);
  assert.deepEqual([v.ok, v.body], [true, { name: "j", model_id: "vertex/gemini-3.7-flash" }]);
  v = R.validateJobBody({ model_id: "vertex/gemini-3.7-flsh" }, all);
  assert.deepEqual([v.ok, v.status, v.body.code, v.body.field], [false, 400, "MODEL_UNKNOWN", "model_id"]);
  assert.ok(v.body.suggestions.includes("vertex/gemini-3.7-flash"));
  v = R.validateJobBody({ model_id: 7 }, all);
  assert.deepEqual([v.ok, v.body.code], [false, "INVALID_MODEL"]);
  v = R.validateJobBody("not an object", all);
  assert.equal(v.ok, true);
});

/* ─── Server wiring (stubbed Next, MCP and network) ──────────── */

const SA = '{"type":"service_account","private_key":"fake"}';
function reset({ settings = { defaultModel: "vertex/gemini-3.1-pro-preview" }, runtime = { GOOGLE_APPLICATION_CREDENTIALS: SA } } = {}) {
  server.bustInstallDefaultModelCache();
  globalThis.__mcp = [];
  globalThis.__proxied = [];
  globalThis.__settings = settings;
  globalThis.__settingsReads = 0;
  globalThis.__runtime = runtime;
}

// The provider store and the vendors: nothing is configured but what the runtime carries.
globalThis.fetch = async (url, init = {}) => {
  const u = new URL(String(url));
  globalThis.__fetched = [...(globalThis.__fetched ?? []), { url: String(url), init }];
  if (u.pathname === "/api/v1/providers") return new Response(JSON.stringify({ instances: [] }), { headers: { "content-type": "application/json" } });
  if (u.pathname === "/api/v1/settings") return new Response(JSON.stringify({ applied: ["x"], cleared: [], rejected: [] }), { status: globalThis.__settingsStatus ?? 200, headers: { "content-type": "application/json" } });
  throw new Error(`unexpected request to ${u.host}`);
};

test("the install default is read from the settings store and cached for 30 seconds; a bust re-reads", async () => {
  reset();
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.1-pro-preview");
  globalThis.__settings = { defaultModel: "vertex/gemini-3.7-flash" };
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.1-pro-preview");
  assert.equal(globalThis.__settingsReads, 1);
  server.bustInstallDefaultModelCache();
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.7-flash");
  assert.equal(globalThis.__settingsReads, 2);
});

test("resolveModelForRequest runs the whole chain against the live registry view", async () => {
  reset({ settings: { defaultModel: "vertex/gemini-3.7-flash" } });
  let { result, installDefault } = await server.resolveModelForRequest({});
  assert.deepEqual([result.ok, result.canonical, result.source, installDefault], [true, "vertex/gemini-3.7-flash", "default", "vertex/gemini-3.7-flash"]);
  ({ result } = await server.resolveModelForRequest({ header: "gemini-3.5-flash", headerProvider: "vertex" }));
  assert.deepEqual([result.canonical, result.source], ["vertex/gemini-3.5-flash", "header"]);
  ({ result } = await server.resolveModelForRequest({ header: "vertex/gemini-1-gone" }));
  assert.deepEqual([result.ok, result.code, result.reason], [false, "MODEL_UNAVAILABLE", "MODEL_UNKNOWN"]);
  reset({ settings: {} });
  ({ result } = await server.resolveModelForRequest({}));
  assert.deepEqual([result.canonical, result.source], ["vertex/gemini-3.1-pro-preview", "derived"]);
  reset({ settings: {}, runtime: {} });
  ({ result } = await server.resolveModelForRequest({}));
  assert.deepEqual([result.ok, result.reason], [false, "NO_PROVIDER_CONFIGURED"]);
});

const put = (body) => settingsRoute.PUT(new Request("http://localhost/api/agent/settings", { method: "PUT", body: typeof body === "string" ? body : JSON.stringify(body) }));
const upstreamPuts = () => (globalThis.__fetched ?? []).filter((c) => c.url.endsWith("/api/v1/settings") && c.init.method === "PUT");

test("settings PUT: an unknown default answers 400 with suggestions and writes nothing", async () => {
  reset();
  globalThis.__fetched = [];
  const res = await put({ updates: { defaultModel: "vertex/gemini-9-imaginary" }, actor: "operator" });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.code, "MODEL_UNKNOWN");
  assert.equal(body.field, "defaultModel");
  assert.ok(body.suggestions.length > 0);
  assert.equal(upstreamPuts().length, 0);
});

test("settings PUT: a good default is forwarded canonical, and only then is the cache dropped", async () => {
  reset();
  globalThis.__fetched = [];
  await server.readInstallDefaultModel();
  const reads = globalThis.__settingsReads;
  globalThis.__settings = { defaultModel: "vertex/gemini-3.7-flash" };
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.1-pro-preview", "still cached");
  const res = await put({ updates: { defaultModel: "gemini-3.7-flash" }, actor: "operator" });
  assert.equal(res.status, 200);
  const [forwarded] = upstreamPuts();
  assert.deepEqual(JSON.parse(forwarded.init.body), { updates: { defaultModel: "vertex/gemini-3.7-flash" }, actor: "operator" });
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.7-flash", "the write dropped the cache");
  assert.equal(globalThis.__settingsReads, reads + 1);
});

test("settings PUT: a refused write leaves the cache alone; clearing the default and other keys pass straight through", async () => {
  reset();
  globalThis.__fetched = [];
  await server.readInstallDefaultModel();
  globalThis.__settings = { defaultModel: "vertex/gemini-3.7-flash" };
  globalThis.__settingsStatus = 500;
  await put({ updates: { defaultLogFormat: "CEF" } });
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.1-pro-preview", "a failed write does not drop the cache");
  globalThis.__settingsStatus = 200;
  const res = await put({ clear: ["defaultModel"] });
  assert.equal(res.status, 200);
  assert.deepEqual(JSON.parse(upstreamPuts().at(-1).init.body), { clear: ["defaultModel"] });
  assert.equal(await server.readInstallDefaultModel(), "vertex/gemini-3.7-flash");
  // A body that is not JSON is the MCP's to reject.
  await put("not json");
  assert.equal(upstreamPuts().at(-1).init.body, "not json");
});

const postJob = (body) => jobsRoute.POST(new Request("http://localhost/api/agent/jobs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }));
const patchJob = (body) => jobRoute.PATCH(
  new Request("http://localhost/api/agent/jobs/nightly", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  { params: Promise.resolve({ jobName: "nightly" }) },
);

test("jobs POST and PATCH: a model the registry rejects answers 400 with suggestions and nothing is saved", async () => {
  reset();
  for (const call of [postJob, patchJob]) {
    globalThis.__proxied = [];
    const res = await call({ name: "nightly", model_id: "vertex/gemini-9-imaginary" });
    assert.equal(res.status, 400);
    const body = await res.json();
    assert.deepEqual([body.code, body.field], ["MODEL_UNKNOWN", "model_id"]);
    assert.ok(body.suggestions.length > 0);
    assert.deepEqual(globalThis.__proxied, []);
  }
});

test("jobs POST and PATCH: a good model is forwarded canonical; '' clears; an absent model_id is untouched", async () => {
  reset();
  for (const [call, path, method] of [[postJob, "/api/v1/jobs", "POST"], [patchJob, "/api/v1/jobs/nightly", "PATCH"]]) {
    globalThis.__proxied = [];
    assert.equal((await call({ name: "nightly", model_id: "gemini-3.7-flash" })).status, 200);
    assert.deepEqual(globalThis.__proxied.map((p) => [p.path, p.method, JSON.parse(p.body)]), [[path, method, { name: "nightly", model_id: "vertex/gemini-3.7-flash" }]]);

    globalThis.__proxied = [];
    assert.equal((await call({ name: "nightly", model_id: "" })).status, 200);
    assert.deepEqual(JSON.parse(globalThis.__proxied[0].body), { name: "nightly", model_id: "" });

    globalThis.__proxied = [];
    assert.equal((await call({ cron: "0 3 * * *" })).status, 200);
    assert.deepEqual(JSON.parse(globalThis.__proxied[0].body), { cron: "0 3 * * *" });
  }
});

test("the models route marks the default and says where it came from", async () => {
  reset({ settings: {} });
  const body = await server.listModelsForApi();
  const def = body.filter((m) => m.isDefault);
  assert.deepEqual(def.map((m) => [m.ref, m.defaultSource]), [["vertex/gemini-3.1-pro-preview", "derived"]]);
});

/* ─── Source guards ──────────────────────────────────────────── */

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.(?:ts|tsx|mjs|md|yaml|yml|sh|example)$/.test(name)) yield full;
  }
}

// The pages and notes that tell an operator the variable was removed have to
// name it; code may not. Only the variable's name is allowed in these files, the
// removed identifiers stay banned everywhere.
const REMOVAL_NOTICE_FILES = new Set(["lib/release-notes.ts", "lib/journeys.ts"]);
const isRemovalNotice = (rel) => rel.startsWith("app/help/") || REMOVAL_NOTICE_FILES.has(rel);

test("GEMINI_MODEL and the bare-id resolver are gone from the agent sources", () => {
  const offenders = [];
  for (const dir of ["app", "lib", "components"]) {
    for (const file of walk(join(root, dir))) {
      const text = readFileSync(file, "utf8");
      const rel = relative(root, file);
      for (const needle of ["GEMINI_MODEL", "resolveModelName", "resolveTurnModel", "DEFAULT_GEMINI_MODEL"]) {
        if (needle === "GEMINI_MODEL" && isRemovalNotice(rel)) continue;
        if (text.includes(needle)) offenders.push(`${rel}: ${needle}`);
      }
    }
  }
  assert.deepEqual(offenders, []);
  assert.ok(!readFileSync(join(root, "lib/runtime-config.ts"), "utf8").includes("GEMINI_MODEL"));
});

test("GEMINI_MODEL is not set anywhere an install is configured", () => {
  const repo = join(root, "..", "..");
  const offenders = [];
  for (const rel of [".env.example", "mcp/agent/.env.local.example", "bundles/phantom-agent.bundle.yaml", "scripts/import_agent_bundle.sh", "a2ui/surfaces/setup.jsonl"]) {
    if (readFileSync(join(repo, rel), "utf8").includes("GEMINI_MODEL")) offenders.push(rel);
  }
  for (const dir of ["installer", "updater"]) {
    try {
      for (const file of walk(join(repo, dir))) if (readFileSync(file, "utf8").includes("GEMINI_MODEL")) offenders.push(relative(repo, file));
    } catch { /* no such directory */ }
  }
  assert.deepEqual(offenders, []);
});

test("the chat route resolves one chain and ends a turn on a rejection with the MODEL_UNAVAILABLE event", () => {
  const src = readFileSync(join(root, "app/api/chat/route.ts"), "utf8");
  assert.match(src, /resolveModelForRequest\(\s*\{ header: requestedModel, headerProvider: requestedProvider, session: sessionModelPref \}/);
  assert.match(src, /action: 'chat_model_rejected'|safeAudit\('chat_model_rejected'/);
  assert.match(src, /code: rejection\.code/);
  // The rejection path ends the stream without a `done`, so a scheduled job counts the run as failed.
  const turn = src.slice(src.indexOf("const { result: turnModel }"), src.indexOf("const modelRef = turnModel.ref"));
  assert.ok(turn.includes("reportModelRejected") && turn.includes("controller.close()") && !turn.includes("'done'"));
  assert.match(src, /override_source: overrideSource/);
  assert.match(src, /turnModel\.source === 'default' \? 'none' : turnModel\.source/);
});

test("the chat route needs no Google credential to run a turn: it never reads Vertex or Gemini credentials itself", () => {
  const src = readFileSync(join(root, "app/api/chat/route.ts"), "utf8");
  // Credentials reach the Gemini adapter only through credsFromRuntimeConfig; any other provider reads its own store in dispatch.
  for (const needle of ["GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "runtimeConfig.GEMINI", "resolveVertexCredentials"]) {
    assert.ok(!src.includes(needle), `route.ts mentions ${needle}`);
  }
  assert.ok(src.includes("credsFromRuntimeConfig(runtimeConfig)"));
});

test("the /cost summary and the cost page name no single vendor for caching or pricing", () => {
  const route = readFileSync(join(root, "app/api/chat/route.ts"), "utf8");
  assert.ok(!route.includes("via Vertex caching"));
  assert.ok(!route.includes("Vertex AI public pricing"));
  const page = readFileSync(join(root, "app/observability/cost/page.tsx"), "utf8");
  assert.ok(!page.includes("Vertex AI public pricing"));
  assert.ok(!page.includes('sub="Vertex prompt cache"'));
});

test("the audit event names and the events filter know chat_model_rejected", () => {
  const names = readFileSync(join(root, "lib/audit-event-names.ts"), "utf8");
  assert.ok(names.includes("chat_model_rejected"), "lib/audit-event-names.ts");
  const events = readFileSync(join(root, "app/observability/events/page.tsx"), "utf8");
  assert.ok(events.includes("chat_model_rejected"), "app/observability/events/page.tsx");
});

for (const { name, fn } of queue) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 7).join("\n     ")); }
}
if (failed) { console.log(`${failed} test(s) failed`); process.exit(1); }
console.log("all passed");
