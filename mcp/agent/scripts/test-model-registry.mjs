#!/usr/bin/env node
/**
 * Model registry (lib/providers/registry/*, lib/providers/credentials.ts,
 * lib/providers/url-guard.ts): merge rules, availability, lifecycle, the live
 * list cache (TTL, last-good, offline), audit rows, reference resolution and
 * the outbound-URL guards.
 *
 *   node scripts/test-model-registry.mjs   (npm run test:model-registry)
 *
 * Everything runs against a fake fetch, a fake resolver and an injected clock.
 * Imports the real TypeScript through Node's type stripping; on a Node without
 * it the test skips (the build type-checks the modules).
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const reg = await import("../lib/providers/registry/registry.ts");
const live = await import("../lib/providers/registry/live.ts");
const { resolveModelRef } = await import("../lib/providers/registry/resolve-ref.ts");
const { CURATED_CATALOG, publishModelFacts } = await import("../lib/providers/registry/lookup.ts");
const guard = await import("../lib/providers/url-guard.ts");
const creds = await import("../lib/providers/credentials.ts");
const { ProviderError } = await import("../lib/providers/errors.ts");

let failed = 0;
const queue = [];
function test(name, fn) {
  queue.push({ name, fn });
}
async function run() {
  for (const { name, fn } of queue) {
    try { await fn(); console.log("ok   " + name); }
    catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
  }
}

/* ─── Fakes ─────────────────────────────────────────────────── */

const T0 = Date.parse("2026-10-13T12:00:00Z");
const MIN = 60_000;
const DAY = 24 * 60 * MIN;
const publicHost = async () => ["203.0.113.10"];

function clock(start = T0) {
  const c = { t: start, now: () => c.t, advance: (ms) => { c.t += ms; } };
  return c;
}

/** A fake fetch. `handler(url, init)` returns {status, body, headers} or throws. */
function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    const r = await handler(String(url), init, calls.length);
    const body = r.raw !== undefined ? r.raw : JSON.stringify(r.body ?? {});
    return new Response(body, { status: r.status ?? 200, headers: r.headers ?? { "content-type": "application/json" } });
  };
  fn.calls = calls;
  return fn;
}

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const K_ANT = ["sk", "ant", "api03", "FAKE".repeat(5)].join("-");
const K_OAI = ["sk", "proj-" + "FAKE".repeat(5)].join("-");
const K_GEM = ["AI", "zaSy", "FAKE".repeat(8)].join("");

function anthropicItem(id, extra = {}) {
  return {
    id,
    type: "model",
    display_name: id,
    max_input_tokens: 1_000_000,
    max_tokens: 128_000,
    lifecycle: "active",
    retires_at: null,
    capabilities: {
      thinking: { types: { adaptive: { supported: true }, enabled: { supported: false }, disabled: { supported: false } } },
      effort: { low: { supported: true }, medium: { supported: true }, high: { supported: true }, max: { supported: true }, xhigh: { supported: true } },
    },
    ...extra,
  };
}

const ANTHROPIC_IDS = ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5", "claude-sonnet-5"];
const OPENAI_IDS = ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"];

/** Routes: anthropic, openai, gemini API. Returns a fetch plus the mutable state. */
function providers(state = {}) {
  const s = {
    anthropic: ANTHROPIC_IDS.map((id) => anthropicItem(id)),
    openai: OPENAI_IDS.map((id) => ({ id, object: "model" })),
    gemini: [{ name: "models/gemini-3.1-pro-preview", displayName: "Gemini 3.1 Pro", inputTokenLimit: 1_048_576, outputTokenLimit: 65_536 }],
    fail: new Set(),
    ...state,
  };
  const f = fakeFetch((url) => {
    const host = new URL(url).host;
    const which = host.includes("anthropic") ? "anthropic" : host.includes("openai") ? "openai" : "gemini";
    if (s.fail.has(which)) return { status: 503, body: { error: { message: "down" } } };
    if (which === "anthropic") return { body: { data: s.anthropic, has_more: false } };
    if (which === "openai") return { body: { object: "list", data: s.openai } };
    return { body: { models: s.gemini } };
  });
  f.state = s;
  return f;
}

const ALL = { vertex: { apiKey: K_GEM }, anthropic: { apiKey: K_ANT }, openai: { apiKey: K_OAI } };

function makeRegistry(f, c, extra = {}) {
  const audits = [];
  const r = reg.createModelRegistry({
    fetch: f,
    resolveHost: publicHost,
    now: c.now,
    audit: (action, row) => { audits.push({ action, ...row }); },
    dispatchable: ["vertex", "anthropic", "openai"],
    publishFacts: false,
    ...extra,
  });
  r.audits = audits;
  return r;
}

const byRef = (entries, ref) => {
  const e = entries.find((x) => x.ref === ref);
  assert.ok(e, `no entry ${ref}`);
  return e;
};

/* ─── Catalog shape ─────────────────────────────────────────── */

test("the catalogs hold the models the design names and none it excludes", () => {
  const ids = (p) => CURATED_CATALOG.filter((m) => m.provider === p && m.kind === "chat").map((m) => m.model);
  assert.deepEqual(ids("anthropic").sort(), [...ANTHROPIC_IDS].sort());
  assert.deepEqual(ids("openai").sort(), [...OPENAI_IDS].sort());
  const vertex = ids("vertex");
  for (const id of ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-3.0-pro", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]) {
    assert.ok(vertex.includes(id), id);
  }
  const all = CURATED_CATALOG.map((m) => m.model).join(" ");
  assert.ok(!/haiku-4|sonnet-4|mythos|codex/.test(all), "no excluded or deprecated ids");
});

test("every entry states its limits, tokenizer, thinking and lifecycle; gaps are flagged, never invented", () => {
  for (const m of CURATED_CATALOG) {
    assert.ok(m.tokenizerFactor >= 1, m.model);
    assert.ok(m.thinking && m.thinking.on && m.thinking.offMode, m.model);
    assert.ok(m.lifecycle && m.lifecycle.stage, m.model);
    if (m.kind === "chat") {
      if (m.contextWindow === null) assert.ok(m.unverified?.includes("contextWindow"), `${m.model} context null but not flagged`);
      if (m.maxOutput === null) assert.ok(m.unverified?.includes("maxOutput"), `${m.model} maxOutput null but not flagged`);
    }
  }
  const claude = CURATED_CATALOG.filter((m) => m.provider === "anthropic");
  assert.ok(claude.every((m) => m.tokenizerFactor === 1.3));
  const gemini = CURATED_CATALOG.filter((m) => m.provider === "vertex");
  assert.ok(gemini.every((m) => m.tokenizerFactor === 1));
});

test("one recommended model per provider", () => {
  for (const p of ["vertex", "anthropic", "openai"]) {
    assert.equal(CURATED_CATALOG.filter((m) => m.provider === p && m.recommended).length, 1, p);
  }
});

test("forced tool choice is off wherever the vendor rejects it or support is unverified", () => {
  const get = (id) => CURATED_CATALOG.find((m) => m.model === id);
  for (const id of ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-sonnet-5"]) {
    assert.equal(get(id).forcedToolChoice, false, id);
  }
  assert.equal(get("claude-haiku-5-5").forcedToolChoice, true);
  assert.deepEqual(get("claude-sonnet-5-5").thinking.offMode, "between_tools");
  assert.deepEqual(get("claude-opus-5-5").thinking.offMode, "low_effort");
  assert.deepEqual(get("claude-haiku-5-5").thinking.offMode, "disabled");
  for (const id of ["claude-opus-5", "claude-sonnet-5"]) assert.ok(get(id).unverified.includes("forcedToolChoice"), id);
});

/* ─── Merge rules ───────────────────────────────────────────── */

test("Anthropic: live wins limits, capabilities and lifecycle; curated wins price, off mode and forced tool choice", async () => {
  const f = providers();
  f.state.anthropic = ANTHROPIC_IDS.map((id) =>
    id === "claude-opus-5-5"
      ? anthropicItem(id, { max_input_tokens: 900_000, max_tokens: 100_000, capabilities: { thinking: { types: { adaptive: { supported: true }, enabled: { supported: false }, disabled: { supported: true } } }, effort: { low: { supported: true }, high: { supported: true } } } })
      : anthropicItem(id),
  );
  const c = clock();
  const entries = await makeRegistry(f, c).list({ creds: ALL });
  const opus = byRef(entries, "anthropic/claude-opus-5-5");
  assert.equal(opus.contextWindow, 900_000);
  assert.equal(opus.maxOutput, 100_000);
  assert.deepEqual([...opus.thinking.efforts], ["low", "high"]);
  assert.equal(opus.thinking.defaultEffort, undefined, "default effort dropped when the live list no longer offers it");
  assert.equal(opus.thinking.offMode, "low_effort", "curated off mode wins even though live says disabled is supported");
  assert.equal(opus.pricing.inputPerM, 4);
  assert.equal(opus.forcedToolChoice, false);
  assert.equal(opus.source, "live+curated");
  assert.equal(opus.liveSeenAt, new Date(T0).toISOString());
  assert.equal(opus.availability, "available");
  assert.ok(!opus.unverified.includes("contextWindow") && !opus.unverified.includes("efforts"));
});

test("a model the live list says cannot be disabled is never asked to disable", async () => {
  const f = providers();
  f.state.anthropic = ANTHROPIC_IDS.map((id) => anthropicItem(id)); // disabled.supported false everywhere
  const entries = await makeRegistry(f, clock()).list({ creds: ALL });
  assert.equal(byRef(entries, "anthropic/claude-haiku-5-5").thinking.offMode, "low_effort");
});

test("Anthropic live-only model: selectable, unpriced, rules derived from its capabilities", async () => {
  const f = providers();
  f.state.anthropic = [...ANTHROPIC_IDS, "claude-future-7"].map((id) =>
    id === "claude-future-7"
      ? anthropicItem(id, { display_name: "Claude Future 7", capabilities: { thinking: { types: { adaptive: { supported: false }, enabled: { supported: true }, disabled: { supported: true } } }, effort: { low: { supported: true } } } })
      : anthropicItem(id),
  );
  const entries = await makeRegistry(f, clock()).list({ creds: ALL });
  const e = byRef(entries, "anthropic/claude-future-7");
  assert.equal(e.availability, "unpriced");
  assert.equal(e.selectable, true);
  assert.equal(e.pricing, null);
  assert.equal(e.source, "live");
  assert.equal(e.displayName, "Claude Future 7");
  assert.equal(e.thinking.on, "enabled_budget");
  assert.equal(e.thinking.offMode, "disabled");
  assert.equal(e.forcedToolChoice, false);
  assert.equal(e.tokenizerFactor, 1.3);
  assert.ok(e.unverified.includes("pricing"));
});

test("OpenAI: the curated table is filtered to what the key can see; live-only chat ids are unverified and not selectable", async () => {
  const f = providers();
  f.state.openai = ["gpt-6-sol", "gpt-6-luna", "gpt-9-future", "text-embedding-3-large", "whisper-1", "dall-e-3", "gpt-image-1", "omni-moderation-latest"].map((id) => ({ id }));
  const entries = await makeRegistry(f, clock()).list({ creds: ALL });
  assert.equal(byRef(entries, "openai/gpt-6-sol").availability, "available");
  assert.equal(byRef(entries, "openai/gpt-6-sol").selectable, true);
  const hidden = byRef(entries, "openai/gpt-6-astra");
  assert.equal(hidden.availability, "unavailable");
  assert.equal(hidden.selectable, false);
  const extra = byRef(entries, "openai/gpt-9-future");
  assert.equal(extra.availability, "unverified");
  assert.equal(extra.selectable, false);
  assert.equal(extra.source, "live");
  for (const id of ["text-embedding-3-large", "whisper-1", "dall-e-3", "gpt-image-1", "omni-moderation-latest"]) {
    assert.ok(!entries.some((e) => e.model === id), `${id} should be dropped`);
  }
});

test("OpenAI with the shipped dispatchable default: every curated model the key sees is selectable, a live-only chat id stays unverified and not selectable", async () => {
  const f = providers();
  f.state.openai = [...OPENAI_IDS, "gpt-9-future", "o9-preview"].map((id) => ({ id }));
  const r = reg.createModelRegistry({ fetch: f, resolveHost: publicHost, now: clock().now, publishFacts: false });
  const entries = await r.list({ creds: { openai: { apiKey: K_OAI } } });
  const openai = entries.filter((e) => e.provider === "openai");
  const curated = openai.filter((e) => OPENAI_IDS.includes(e.model));
  assert.equal(curated.length, OPENAI_IDS.length);
  for (const e of curated) {
    assert.equal(e.selectable, true, e.ref);
    assert.notEqual(e.availability, "unverified", e.ref);
    assert.equal(e.reason === undefined || !/Chat cannot run/.test(e.reason), true, e.ref);
  }
  for (const id of ["gpt-9-future", "o9-preview"]) {
    const e = byRef(entries, `openai/${id}`);
    assert.equal(e.availability, "unverified", id);
    assert.equal(e.selectable, false, id);
    assert.equal(e.source, "live");
  }
});

test("OpenAI with no list reachable at all: the curated entries are shown as unverified and are not selectable (a model the key may not see)", async () => {
  const f = providers();
  f.state.fail.add("openai");
  const r = reg.createModelRegistry({ fetch: f, resolveHost: publicHost, now: clock().now, publishFacts: false });
  const entries = await r.list({ creds: { openai: { apiKey: K_OAI } } });
  const sol = byRef(entries, "openai/gpt-6-sol");
  assert.equal(sol.availability, "unverified");
  assert.equal(sol.selectable, false);
  assert.equal(sol.providerState, "offline");
});

test("Vertex with a Gemini API key: the live list enriches limits; a model missing from it is unverified but stays selectable; live-only ids are ignored", async () => {
  const f = providers();
  f.state.gemini = [
    { name: "models/gemini-3.1-pro-preview", inputTokenLimit: 1_048_576, outputTokenLimit: 65_536 },
    { name: "models/gemma-3-27b-it", inputTokenLimit: 131_072 },
  ];
  const entries = await makeRegistry(f, clock()).list({ creds: ALL });
  const pro = byRef(entries, "vertex/gemini-3.1-pro-preview");
  assert.equal(pro.contextWindow, 1_048_576);
  assert.equal(pro.availability, "available");
  assert.equal(pro.source, "live+curated");
  const flash = byRef(entries, "vertex/gemini-3.7-flash");
  assert.equal(flash.availability, "unverified");
  assert.equal(flash.selectable, true);
  assert.ok(!entries.some((e) => e.model === "gemma-3-27b-it"));
  assert.equal(f.calls.filter((c) => c.url.includes("generativelanguage")).length, 1);
  assert.ok(f.calls.every((c) => !c.url.includes(K_GEM)), "the Gemini key is never in a URL");
  assert.equal(f.calls.find((c) => c.url.includes("generativelanguage")).init.headers["x-goog-api-key"], K_GEM);
});

test("Vertex with a service account only: nothing is fetched, entries are unverified and selectable", async () => {
  const f = providers();
  const entries = await makeRegistry(f, clock()).list({ creds: { vertex: { serviceAccountJson: "{}" } } });
  assert.equal(f.calls.length, 0);
  const e = byRef(entries, "vertex/gemini-3.1-pro-preview");
  assert.equal(e.availability, "unverified");
  assert.equal(e.selectable, true);
  assert.equal(e.providerState, "unchecked");
  assert.match(e.reason, /Verify/);
});

test("providers without credentials contribute not_configured, not selectable entries", async () => {
  const entries = await makeRegistry(providers(), clock()).list({ creds: { vertex: { apiKey: K_GEM } } });
  for (const e of entries.filter((x) => x.provider !== "vertex")) {
    assert.equal(e.availability, "not_configured", e.ref);
    assert.equal(e.selectable, false, e.ref);
    assert.equal(e.providerState, "not_configured");
    assert.match(e.reason, /Providers page/);
  }
});

test("a configured key does not make a provider selectable unless this build can run it", async () => {
  const entries = await makeRegistry(providers(), clock(), { dispatchable: ["vertex"] }).list({ creds: ALL });
  const opus = byRef(entries, "anthropic/claude-opus-5-5");
  assert.equal(opus.availability, "available");
  assert.equal(opus.selectable, false);
  assert.match(opus.reason, /Chat cannot run on Anthropic models on this install/);
  assert.equal(byRef(entries, "vertex/gemini-3.1-pro-preview").selectable, true);
  assert.deepEqual([...reg.DISPATCHABLE_PROVIDERS], ["vertex", "anthropic", "openai"], "the shipped default: Gemini, Claude and OpenAI adapters exist");
});

test("non-chat models are listed but never selectable", async () => {
  const entries = await makeRegistry(providers(), clock()).list({ creds: ALL });
  for (const id of ["gemini-embedding-001", "text-embedding-005", "imagen-4.0-generate-preview", "chirp-3-hd"]) {
    const e = byRef(entries, `vertex/${id}`);
    assert.equal(e.selectable, false, id);
    assert.equal(e.reason, "Not a chat model.");
  }
});

test("the Gemini 2.5 family is deprecated yet selectable, with no retirement date to hide it on", async () => {
  const entries = await makeRegistry(providers(), clock(Date.parse("2027-06-01T00:00:00Z"))).list({ creds: ALL });
  for (const id of ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]) {
    const e = byRef(entries, `vertex/${id}`);
    assert.equal(e.availability, "deprecated", id);
    assert.equal(e.selectable, true, id);
    assert.equal(e.lifecycle.retiresAt, undefined, id);
  }
});

/* ─── Lifecycle ─────────────────────────────────────────────── */

function withShutdown(date) {
  const f = providers();
  f.state.openai = OPENAI_IDS.map((id) => (id === "gpt-6-sol" ? { id, shutdown_date: date } : { id }));
  return f;
}
const iso = (ms) => new Date(ms).toISOString();

test("a past retirement date retires the model: hidden by default, present on request, never selectable", async () => {
  const f = withShutdown(iso(T0 - DAY));
  const r = makeRegistry(f, clock());
  const shown = await r.list({ creds: ALL });
  assert.ok(!shown.some((e) => e.ref === "openai/gpt-6-sol"));
  const all = await r.list({ creds: ALL, includeRetired: true });
  const e = byRef(all, "openai/gpt-6-sol");
  assert.equal(e.availability, "retired");
  assert.equal(e.selectable, false);
  assert.match(e.reason, /Retired on 2026-10-12/);
});

test("within 30 days of retirement the model is deprecated: badge, still selectable; the window edges", async () => {
  const cases = [
    [iso(T0 + 10 * DAY), "deprecated"],
    [iso(T0 + 30 * DAY), "deprecated"],
    [iso(T0 + 30 * DAY + 1000), "available"],
    [iso(T0 + 1000), "deprecated"],
    [iso(T0), "retired"],
  ];
  for (const [date, want] of cases) {
    const entries = await makeRegistry(withShutdown(date), clock()).list({ creds: ALL, includeRetired: true });
    const e = byRef(entries, "openai/gpt-6-sol");
    assert.equal(e.availability, want, date);
    assert.equal(e.selectable, want !== "retired", date);
    if (want === "deprecated") assert.match(e.reason, /retires on/);
  }
});

test("shutdown_date accepts a date string or a unix timestamp", () => {
  assert.equal(live.parseShutdownDate("2026-12-11"), "2026-12-11T00:00:00.000Z");
  assert.equal(live.parseShutdownDate(1796947200), new Date(1796947200 * 1000).toISOString());
  assert.equal(live.parseShutdownDate("1796947200"), new Date(1796947200 * 1000).toISOString());
  assert.equal(live.parseShutdownDate(null), undefined);
  assert.equal(live.parseShutdownDate("soon"), undefined);
});

test("Anthropic lifecycle from the live list: deprecated and retired", async () => {
  const f = providers();
  f.state.anthropic = ANTHROPIC_IDS.map((id) =>
    id === "claude-opus-5" ? anthropicItem(id, { lifecycle: "deprecated", retires_at: iso(T0 + 90 * DAY) })
      : id === "claude-sonnet-5" ? anthropicItem(id, { lifecycle: "retired", retires_at: iso(T0 - DAY) })
      : anthropicItem(id));
  const entries = await makeRegistry(f, clock()).list({ creds: ALL, includeRetired: true });
  assert.equal(byRef(entries, "anthropic/claude-opus-5").availability, "deprecated");
  assert.equal(byRef(entries, "anthropic/claude-opus-5").selectable, true);
  assert.equal(byRef(entries, "anthropic/claude-sonnet-5").availability, "retired");
});

test("pricing that has expired shows the model as unpriced", async () => {
  const before = await makeRegistry(providers(), clock(Date.parse("2026-11-21T10:00:00Z"))).list({ creds: ALL });
  assert.equal(byRef(before, "openai/gpt-5.6-sol").availability, "available");
  const after = await makeRegistry(providers(), clock(Date.parse("2026-11-22T10:00:00Z"))).list({ creds: ALL });
  assert.equal(byRef(after, "openai/gpt-5.6-sol").availability, "unpriced");
  assert.equal(byRef(after, "openai/gpt-5.6-sol").selectable, true);
});

/* ─── Cache: TTL, last-good, offline, audit ─────────────────── */

test("a live list is reused for 10 minutes, then fetched again", async () => {
  const f = providers();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  assert.equal(f.calls.length, 3);
  c.advance(9 * MIN + 59_000);
  await r.list({ creds: ALL });
  assert.equal(f.calls.length, 3, "still fresh");
  c.advance(2000);
  await r.list({ creds: ALL });
  await r.idle();
  assert.equal(f.calls.length, 6, "refetched after the TTL, in the background");
});

test("concurrent listings share one request per provider", async () => {
  const f = providers();
  const r = makeRegistry(f, clock());
  await Promise.all([r.list({ creds: ALL }), r.list({ creds: ALL }), r.list({ creds: ALL })]);
  assert.equal(f.calls.length, 3);
});

test("a failed refresh leaves the last good list served as stale, for up to 24 hours, and is not retried for a minute", async () => {
  const f = providers();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  f.state.fail.add("anthropic");
  c.advance(11 * MIN);
  // The call that finds the list expired is answered from the old list at once; the refresh runs behind it.
  const first = await r.list({ creds: ALL });
  assert.equal(byRef(first, "anthropic/claude-opus-5-5").providerState, "live", "no failure is known yet");
  await r.idle();
  const stale = await r.list({ creds: ALL });
  const e = byRef(stale, "anthropic/claude-opus-5-5");
  assert.equal(e.providerState, "stale");
  assert.equal(e.availability, "available");
  assert.equal(e.liveSeenAt, new Date(T0).toISOString(), "liveSeenAt is when the good list was fetched");
  assert.match(e.refreshError, /Anthropic model list failed \(HTTP 503\)/);
  const anthropicCalls = () => f.calls.filter((x) => x.url.includes("anthropic")).length;
  assert.equal(anthropicCalls(), 2);
  c.advance(30_000);
  await r.list({ creds: ALL });
  await r.idle();
  assert.equal(anthropicCalls(), 2, "backing off");
  c.advance(31_000);
  await r.list({ creds: ALL });
  await r.idle();
  assert.equal(anthropicCalls(), 3, "retried after the back-off");
  // Past 24 hours the stale list is dropped.
  c.advance(25 * 60 * MIN);
  const gone = await r.list({ creds: ALL });
  assert.equal(byRef(gone, "anthropic/claude-opus-5-5").providerState, "offline");
});

/** A fetch that answers instantly until `hold` is set; held requests wait for `release()` or an abort. */
function gatedProviders() {
  const f = providers();
  const real = f;
  const gate = { held: false, waiting: [], release() { const w = gate.waiting.splice(0); w.forEach((fn) => fn()); } };
  const wrapped = async (url, init) => {
    if (gate.held) {
      await new Promise((resolve, reject) => {
        gate.waiting.push(resolve);
        init.signal?.addEventListener("abort", () => reject(init.signal.reason));
      });
    }
    return real(url, init);
  };
  wrapped.calls = real.calls;
  wrapped.state = real.state;
  return { f: wrapped, gate, state: real.state };
}

test("stale-while-revalidate: past the TTL a listing is answered from the last good list at once, with the refresh left running in the background", async () => {
  const { f, gate, state } = gatedProviders();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  c.advance(11 * MIN);
  // Anthropic now lists a new model, but its answer is held.
  state.anthropic = [...ANTHROPIC_IDS, "claude-new-9"].map((id) => anthropicItem(id));
  gate.held = true;
  const started = Date.now();
  const during = await r.list({ creds: ALL });
  assert.ok(Date.now() - started < 200, "the listing did not wait for the vendor");
  assert.ok(!during.some((e) => e.model === "claude-new-9"), "answered from the old list");
  assert.equal(byRef(during, "anthropic/claude-opus-5-5").providerState, "live");
  assert.equal(byRef(during, "anthropic/claude-opus-5-5").selectable, true);
  gate.held = false;
  gate.release();
  await r.idle();
  const after = await r.list({ creds: ALL });
  assert.ok(after.some((e) => e.model === "claude-new-9"), "the next listing has the refreshed list");
});

test("stale-while-revalidate: one refresh per provider in flight, however many listings arrive meanwhile", async () => {
  const { f, gate } = gatedProviders();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  assert.equal(f.calls.length, 3);
  c.advance(11 * MIN);
  gate.held = true;
  await Promise.all([r.list({ creds: ALL }), r.list({ creds: ALL }), r.list({ creds: ALL })]);
  await r.list({ creds: ALL });
  gate.held = false;
  gate.release();
  await r.idle();
  assert.equal(f.calls.length, 6, "three providers refreshed once each");
});

test("stale-while-revalidate: the refresh is still bounded by its own deadline, and its failure starts the back-off", async () => {
  const { f, gate } = gatedProviders();
  const c = clock();
  const r = makeRegistry(f, c, { refreshDeadlineMs: 40 });
  await r.list({ creds: ALL });
  c.advance(11 * MIN);
  gate.held = true;
  await r.list({ creds: ALL });
  const started = Date.now();
  await r.idle();
  assert.ok(Date.now() - started < 1000, "idle() returned once the deadline fired, not when the vendor answered");
  const failures = r.audits.filter((a) => a.action === "provider_models_refresh_failed");
  assert.equal(failures.length, 3);
  assert.ok(failures.every((a) => /did not answer in time/.test(a.metadata.message)));
  const calls = f.calls.length;
  const stale = await r.list({ creds: ALL });
  await r.idle();
  assert.equal(byRef(stale, "anthropic/claude-opus-5-5").providerState, "stale");
  assert.match(byRef(stale, "anthropic/claude-opus-5-5").refreshError, /did not answer in time/);
  assert.equal(f.calls.length, calls, "backing off: no new request inside the minute");
  gate.held = false;
  c.advance(61_000);
  await r.list({ creds: ALL });
  await r.idle();
  assert.equal(f.calls.length, calls + 3, "retried after the back-off");
});

test("stale-while-revalidate: with no list at all the first call still waits for the vendor (the cold start is not served curated-only)", async () => {
  const { f, gate } = gatedProviders();
  const r = makeRegistry(f, clock());
  gate.held = true;
  let settled = false;
  const pending = r.list({ creds: { openai: { apiKey: K_OAI } } }).then((entries) => { settled = true; return entries; });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(settled, false, "waiting for the first list");
  gate.held = false;
  gate.release();
  const entries = await pending;
  const sol = byRef(entries, "openai/gpt-6-sol");
  assert.equal(sol.availability, "available");
  assert.equal(sol.selectable, true, "an OpenAI model is selectable on the very first turn");
});

test("stale-while-revalidate: a changed credential and a list older than 24 hours both wait for a fresh fetch", async () => {
  const { f, gate } = gatedProviders();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  gate.held = true;
  let settled = false;
  const rotated = r.list({ creds: { ...ALL, anthropic: { apiKey: K_ANT + "-OTHER" } } }).then(() => { settled = true; });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(settled, false, "the old key's list is not served for the new key; the call waits");
  gate.held = false;
  gate.release();
  await rotated;
  c.advance(25 * 60 * MIN);
  gate.held = true;
  settled = false;
  const aged = r.list({ creds: ALL }).then(() => { settled = true; });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(settled, false, "a list older than 24 hours is not served");
  gate.held = false;
  gate.release();
  await aged;
});

test("a refresh that stalls hits the overall deadline: the lookup, a hung request, or a slow page", async () => {
  const stalled = [
    ["a host-name lookup that never answers", { fetch: providers(), resolveHost: () => new Promise(() => {}) }],
    ["a request that never answers", { fetch: (url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason))), resolveHost: publicHost, timeoutMs: 60_000 }],
  ];
  for (const [label, extra] of stalled) {
    const r = reg.createModelRegistry({
      now: clock().now, publishFacts: false, dispatchable: ["vertex", "anthropic", "openai"], refreshDeadlineMs: 40,
      audit: (action, row) => { audits.push({ action, ...row }); },
      ...extra,
    });
    const audits = [];
    const started = Date.now();
    const entries = await r.list({ creds: { anthropic: { apiKey: K_ANT } } });
    assert.ok(Date.now() - started < 1000, `${label}: the listing waited ${Date.now() - started} ms`);
    const e = byRef(entries, "anthropic/claude-opus-5-5");
    assert.equal(e.providerState, "offline", label);
    assert.equal(e.availability, "unverified", label);
    assert.match(e.refreshError, /did not answer in time/, label);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(audits.filter((a) => a.action === "provider_models_refresh_failed").length, 1, label);
    // And it is not retried at once.
    await r.list({ creds: { anthropic: { apiKey: K_ANT } } });
    assert.equal(audits.filter((a) => a.action === "provider_models_refresh_failed").length, 1, `${label}: backing off`);
  }
});

test("recovery after a failure returns to live", async () => {
  const f = providers();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  f.state.fail.add("openai");
  c.advance(11 * MIN);
  await r.list({ creds: ALL });
  await r.idle();
  f.state.fail.delete("openai");
  c.advance(2 * MIN);
  // This call is answered from the stale list and starts the refresh that recovers.
  const during = await r.list({ creds: ALL });
  assert.equal(byRef(during, "openai/gpt-6-sol").providerState, "stale");
  await r.idle();
  const back = await r.list({ creds: ALL });
  const e = byRef(back, "openai/gpt-6-sol");
  assert.equal(e.providerState, "live");
  assert.equal(e.refreshError, undefined);
});

test("offline with no good list: curated rows are unverified, selectable for Anthropic and Vertex but not OpenAI", async () => {
  const f = providers();
  f.state.fail.add("anthropic");
  f.state.fail.add("openai");
  f.state.fail.add("gemini");
  const entries = await makeRegistry(f, clock()).list({ creds: ALL });
  const claude = byRef(entries, "anthropic/claude-opus-5-5");
  assert.equal(claude.availability, "unverified");
  assert.equal(claude.selectable, true);
  assert.equal(claude.providerState, "offline");
  assert.equal(claude.source, "curated");
  assert.equal(claude.pricing.inputPerM, 4, "curated metadata still served");
  const gpt = byRef(entries, "openai/gpt-6-sol");
  assert.equal(gpt.availability, "unverified");
  assert.equal(gpt.selectable, false);
  assert.equal(byRef(entries, "vertex/gemini-3.1-pro-preview").selectable, true);
});

test("a different credential never sees the previous credential's list", async () => {
  const f = providers();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  f.state.fail.add("anthropic");
  const rotated = await r.list({ creds: { ...ALL, anthropic: { apiKey: K_ANT + "-OTHER" } } });
  const e = byRef(rotated, "anthropic/claude-opus-5-5");
  assert.equal(e.providerState, "offline", "the old list is not served for the new key");
  assert.equal(f.calls.filter((x) => x.url.includes("anthropic")).length, 2, "fetched again at once");
});

test("bust drops the cached list", async () => {
  const f = providers();
  const r = makeRegistry(f, clock());
  await r.list({ creds: ALL });
  r.bust("openai");
  await r.list({ creds: ALL });
  assert.equal(f.calls.filter((x) => x.url.includes("openai")).length, 2);
  assert.equal(f.calls.filter((x) => x.url.includes("anthropic")).length, 1);
  r.bust();
  await r.list({ creds: ALL });
  assert.equal(f.calls.length, 3 + 1 + 3);
});

test("audit rows: refreshed on success, refresh_failed on failure, neither carries a credential or a URL", async () => {
  const f = providers();
  const c = clock();
  const r = makeRegistry(f, c);
  await r.list({ creds: ALL });
  f.state.fail.add("openai");
  c.advance(11 * MIN);
  await r.list({ creds: ALL });
  await r.idle();
  const ok = r.audits.filter((a) => a.action === "provider_models_refreshed");
  const bad = r.audits.filter((a) => a.action === "provider_models_refresh_failed");
  assert.equal(ok.length, 3 + 2, "three at first, then anthropic and the Gemini API again");
  assert.equal(bad.length, 1);
  const first = ok.find((a) => a.metadata.provider === "anthropic");
  assert.equal(first.status, "success");
  assert.equal(first.metadata.model_count, ANTHROPIC_IDS.length);
  assert.equal(bad[0].status, "failure");
  assert.equal(bad[0].metadata.provider, "openai");
  assert.equal(bad[0].metadata.error_kind, "unavailable");
  assert.equal(bad[0].metadata.status, 503);
  const blob = JSON.stringify(r.audits);
  for (const secret of [K_ANT, K_OAI, K_GEM]) assert.ok(!blob.includes(secret), "audit rows carry no key");
  assert.ok(!/https?:\/\//.test(blob), "audit rows carry no URL");
});

test("a failing audit sink never breaks a listing", async () => {
  const r = reg.createModelRegistry({
    fetch: providers(), resolveHost: publicHost, now: clock().now, publishFacts: false,
    audit: () => { throw new Error("sink down"); },
  });
  assert.ok((await r.list({ creds: ALL })).length > 10);
  const r2 = reg.createModelRegistry({
    fetch: providers(), resolveHost: publicHost, now: clock().now, publishFacts: false,
    audit: async () => { throw new Error("sink down"); },
  });
  assert.ok((await r2.list({ creds: ALL })).length > 10);
});

test("the cache key is a hash of the credential, not the credential", () => {
  const a = reg.credentialCacheKey("anthropic", { apiKey: K_ANT });
  assert.match(a, /^[0-9a-f]{64}$/);
  assert.ok(!a.includes(K_ANT));
  assert.notEqual(a, reg.credentialCacheKey("anthropic", { apiKey: K_ANT + "x" }));
  assert.notEqual(a, reg.credentialCacheKey("anthropic", { apiKey: K_ANT, baseUrl: "https://gw.example.com" }));
  assert.notEqual(reg.credentialCacheKey("openai", { apiKey: "k", organization: "a" }), reg.credentialCacheKey("openai", { apiKey: "k", organization: "b" }));
});

test("listing publishes live facts for the synchronous lookups", async () => {
  const f = providers();
  f.state.gemini = [{ name: "models/gemini-3.7-flash", inputTokenLimit: 1_048_576 }];
  const r = reg.createModelRegistry({ fetch: f, resolveHost: publicHost, now: clock().now });
  try {
    await r.list({ creds: ALL });
    const caps = await import("../lib/model-context-caps.ts");
    assert.equal(caps.resolveContextCap("gemini-3.7-flash"), 1_048_576);
  } finally {
    publishModelFacts([]);
  }
});

/* ─── Reference resolution ──────────────────────────────────── */

async function allEntries(extra = {}, creds = ALL) {
  return await makeRegistry(providers(), clock(), extra).list({ creds, includeRetired: true });
}

test("provider/model resolves to the canonical ref; a bare id resolves when exactly one configured provider has it", async () => {
  const entries = await allEntries();
  for (const input of ["vertex/gemini-3.1-pro-preview", "gemini-3.1-pro-preview", "Gemini-3.1-Pro-Preview", " vertex/GEMINI-3.1-PRO-PREVIEW "]) {
    const r = resolveModelRef(input, entries);
    assert.equal(r.ok, true, input);
    assert.equal(r.canonical, "vertex/gemini-3.1-pro-preview");
    assert.deepEqual(r.ref, { provider: "vertex", model: "gemini-3.1-pro-preview" });
  }
  assert.equal(resolveModelRef("claude-opus-5-5", entries).canonical, "anthropic/claude-opus-5-5");
  assert.equal(resolveModelRef("gpt-6.1-sol", entries).canonical, "openai/gpt-6.1-sol");
});

test("a bare id offered by two configured providers is AMBIGUOUS and lists the qualified options", async () => {
  const dup = CURATED_CATALOG.filter((m) => m.model === "claude-opus-5-5").map((m) => ({ ...m, provider: "vertex" }));
  const catalog = [...CURATED_CATALOG, ...dup];
  const entries = await allEntries({ catalog });
  const r = resolveModelRef("claude-opus-5-5", entries);
  assert.equal(r.ok, false);
  assert.equal(r.code, "AMBIGUOUS");
  assert.deepEqual([...r.options].sort(), ["anthropic/claude-opus-5-5", "vertex/claude-opus-5-5"]);
  assert.match(r.message, /vertex\/claude-opus-5-5/);
  assert.equal(resolveModelRef("anthropic/claude-opus-5-5", entries).ok, true, "qualifying resolves it");
  assert.equal(resolveModelRef("vertex/claude-opus-5-5", entries).ok, true);
  // Only one of the two configured: the bare id is no longer ambiguous.
  const anthropicOnly = await allEntries({ catalog }, { anthropic: { apiKey: K_ANT } });
  assert.equal(resolveModelRef("claude-opus-5-5", anthropicOnly).canonical, "anthropic/claude-opus-5-5");
});

test("MODEL_UNKNOWN names suggestions that are selectable refs", async () => {
  const entries = await allEntries();
  const r = resolveModelRef("gemini-3.1-pro", entries);
  assert.equal(r.ok, false);
  assert.equal(r.code, "MODEL_UNKNOWN");
  assert.equal(r.suggestions[0], "vertex/gemini-3.1-pro-preview");
  assert.ok(r.suggestions.length <= 3);
  for (const s of r.suggestions) assert.equal(byRef(entries, s).selectable, true);
  assert.equal(resolveModelRef("vertex/not-a-model", entries).code, "MODEL_UNKNOWN");
  assert.equal(resolveModelRef("foo/gemini-2.5-pro", entries).code, "MODEL_UNKNOWN");
  assert.equal(resolveModelRef("", entries).code, "MODEL_UNKNOWN");
  assert.equal(resolveModelRef("   ", entries).code, "MODEL_UNKNOWN");
});

test("PROVIDER_NOT_CONFIGURED, qualified and bare", async () => {
  const entries = await allEntries({}, { vertex: { apiKey: K_GEM } });
  const qualified = resolveModelRef("anthropic/claude-opus-5-5", entries);
  assert.equal(qualified.code, "PROVIDER_NOT_CONFIGURED");
  assert.match(qualified.message, /Anthropic/);
  const bare = resolveModelRef("gpt-6-sol", entries);
  assert.equal(bare.code, "PROVIDER_NOT_CONFIGURED");
  assert.match(bare.message, /OpenAI/);
});

test("MODEL_NOT_SELECTABLE carries the reason", async () => {
  const gated = await allEntries({ dispatchable: ["vertex"] });
  const a = resolveModelRef("anthropic/claude-opus-5-5", gated);
  assert.equal(a.code, "MODEL_NOT_SELECTABLE");
  assert.match(a.message, /Chat cannot run on Anthropic/);
  const embedding = resolveModelRef("text-embedding-005", await allEntries());
  assert.equal(embedding.code, "MODEL_NOT_SELECTABLE");
  assert.match(embedding.message, /Not a chat model/);
  const f = providers();
  f.state.openai = OPENAI_IDS.map((id) => (id === "gpt-6-sol" ? { id, shutdown_date: iso(T0 - DAY) } : { id }));
  const retired = await makeRegistry(f, clock()).list({ creds: ALL, includeRetired: true });
  const r = resolveModelRef("gpt-6-sol", retired);
  assert.equal(r.code, "MODEL_NOT_SELECTABLE");
  assert.match(r.message, /Retired/);
  const hidden = resolveModelRef("gpt-9-future", await makeRegistry(Object.assign(providers(), {}), clock()).list({ creds: ALL }));
  assert.equal(hidden.code, "MODEL_UNKNOWN");
});

/* ─── Live fetchers ─────────────────────────────────────────── */

test("Anthropic list: limit=1000, paged with after_id, bearer auth, version header, no redirects, key never in the URL", async () => {
  const pages = [
    { data: [anthropicItem("claude-a"), anthropicItem("claude-b")], has_more: true, last_id: "claude-b" },
    { data: [anthropicItem("claude-c")], has_more: false, last_id: "claude-c" },
  ];
  const f = fakeFetch((url, init, n) => ({ body: pages[n - 1] }));
  const models = await live.fetchAnthropicModels({ apiKey: K_ANT }, { fetch: f, resolveHost: publicHost });
  assert.deepEqual(models.map((m) => m.id), ["claude-a", "claude-b", "claude-c"]);
  assert.equal(f.calls.length, 2);
  assert.equal(new URL(f.calls[0].url).searchParams.get("limit"), "1000");
  assert.equal(new URL(f.calls[0].url).searchParams.get("after_id"), null);
  assert.equal(new URL(f.calls[1].url).searchParams.get("after_id"), "claude-b");
  assert.equal(new URL(f.calls[0].url).origin, "https://api.anthropic.com");
  for (const call of f.calls) {
    assert.equal(call.init.redirect, "manual");
    assert.equal(call.init.method, "GET");
    assert.equal(call.init.headers.Authorization, `Bearer ${K_ANT}`);
    assert.equal(call.init.headers["anthropic-version"], "2023-06-01");
    assert.ok(!call.url.includes(K_ANT));
    assert.ok(call.init.signal, "a deadline is set");
  }
});

test("Anthropic list parsing: limits, lifecycle, retirement, thinking and effort capabilities", () => {
  const m = live.parseAnthropicModel(anthropicItem("claude-x", { lifecycle: "deprecated", retires_at: "2027-01-01T00:00:00Z" }));
  assert.deepEqual(m, {
    id: "claude-x", displayName: "claude-x", contextWindow: 1_000_000, maxOutput: 128_000,
    lifecycle: "deprecated", retiresAt: "2027-01-01T00:00:00Z",
    capabilities: { thinkingAdaptive: true, thinkingEnabled: false, thinkingDisabled: false, efforts: ["low", "medium", "high", "max", "xhigh"] },
  });
  assert.equal(live.parseAnthropicModel({ nope: 1 }), null);
  assert.equal(live.parseAnthropicModel(null), null);
  const nullXhigh = live.parseAnthropicModel(anthropicItem("claude-y", { capabilities: { effort: { low: { supported: true }, xhigh: null } } }));
  assert.deepEqual(nullXhigh.capabilities.efforts, ["low"]);
});

test("OpenAI list: bearer auth, optional organization and project headers, custom base URL", async () => {
  const f = fakeFetch(() => ({ body: { data: [{ id: "gpt-6-sol" }, { id: "gpt-6-luna", shutdown_date: "2027-01-01" }] } }));
  const models = await live.fetchOpenAiModels(
    { apiKey: K_OAI, organization: "org-fake", project: "proj-fake", baseUrl: "https://gateway.example.com/openai/v1/" },
    { fetch: f, resolveHost: publicHost },
  );
  assert.deepEqual(models, [{ id: "gpt-6-sol" }, { id: "gpt-6-luna", retiresAt: "2027-01-01T00:00:00.000Z" }]);
  assert.equal(f.calls[0].url, "https://gateway.example.com/openai/v1/models");
  const h = f.calls[0].init.headers;
  assert.equal(h.Authorization, `Bearer ${K_OAI}`);
  assert.equal(h["OpenAI-Organization"], "org-fake");
  assert.equal(h["OpenAI-Project"], "proj-fake");
  const plain = fakeFetch(() => ({ body: { data: [] } }));
  await live.fetchOpenAiModels({ apiKey: K_OAI }, { fetch: plain, resolveHost: publicHost });
  assert.equal(plain.calls[0].url, "https://api.openai.com/v1/models");
  assert.equal(plain.calls[0].init.headers["OpenAI-Organization"], undefined);
});

test("Gemini API list: key in a header, pages followed, the models/ prefix removed", async () => {
  const pages = [
    { models: [{ name: "models/gemini-a", displayName: "A", inputTokenLimit: 100, outputTokenLimit: 10 }], nextPageToken: "tok" },
    { models: [{ name: "models/gemini-b" }] },
  ];
  const f = fakeFetch((u, i, n) => ({ body: pages[n - 1] }));
  const models = await live.fetchGeminiApiModels({ apiKey: K_GEM }, { fetch: f, resolveHost: publicHost });
  assert.deepEqual(models, [{ id: "gemini-a", displayName: "A", contextWindow: 100, maxOutput: 10 }, { id: "gemini-b" }]);
  assert.equal(new URL(f.calls[1].url).searchParams.get("pageToken"), "tok");
  for (const call of f.calls) {
    assert.ok(!call.url.includes(K_GEM));
    assert.equal(call.init.headers["x-goog-api-key"], K_GEM);
  }
});

test("Vertex without a Gemini API key has no live list", async () => {
  const f = fakeFetch(() => ({ body: {} }));
  assert.equal(await live.fetchLiveModels("vertex", { serviceAccountJson: "{}" }, { fetch: f }), null);
  assert.equal(f.calls.length, 0);
});

test("errors: status kinds, JSON error text redacted, non-JSON bodies never reflected", async () => {
  const cases = [
    [401, "auth", { error: { message: `invalid x-api-key ${K_ANT}` } }],
    [403, "permission", { error: { message: "no access" } }],
    [429, "rate_limit", { error: { message: "slow down" } }],
    [500, "unavailable", { error: { message: "oops" } }],
    [529, "overloaded", { error: { message: "busy" } }],
    [400, "invalid_request", { error: { message: "bad" } }],
  ];
  for (const [status, kind, body] of cases) {
    const f = fakeFetch(() => ({ status, body, headers: { "content-type": "application/json", "retry-after": "7", "request-id": "req_123" } }));
    await assert.rejects(
      () => live.fetchAnthropicModels({ apiKey: K_ANT }, { fetch: f, resolveHost: publicHost }),
      (e) => {
        assert.ok(e instanceof ProviderError);
        assert.equal(e.kind, kind);
        assert.equal(e.status, status);
        assert.ok(!e.message.includes(K_ANT), "key redacted");
        assert.match(e.message, new RegExp(`HTTP ${status}`));
        if (status === 429) assert.equal(e.retryAfterMs, 7000);
        if (status >= 500 || status === 429) assert.equal(e.retryable, true);
        assert.equal(e.requestId, "req_123");
        return true;
      },
    );
  }
  const html = fakeFetch(() => ({ status: 502, raw: "<html>internal-host-7 secret-banner</html>", headers: { "content-type": "text/html" } }));
  await assert.rejects(
    () => live.fetchOpenAiModels({ apiKey: K_OAI }, { fetch: html, resolveHost: publicHost }),
    (e) => { assert.ok(!/internal-host-7|secret-banner/.test(e.message)); assert.match(e.message, /HTTP 502/); return true; },
  );
});

test("a redirect is a failure and is never followed", async () => {
  const f = fakeFetch(() => ({ status: 302, headers: { location: "https://evil.example.net/steal" } }));
  await assert.rejects(
    () => live.fetchOpenAiModels({ apiKey: K_OAI }, { fetch: f, resolveHost: publicHost }),
    (e) => e instanceof ProviderError && e.code === "BASE_URL_REDIRECT" && e.status === 302,
  );
  assert.equal(f.calls.length, 1, "no second request");
  assert.equal(f.calls[0].init.redirect, "manual");
});

test("a network failure and a timeout are network errors", async () => {
  const down = async () => { throw new TypeError("fetch failed: connect ECONNREFUSED 10.0.0.9:443 /secret/path"); };
  await assert.rejects(
    () => live.fetchOpenAiModels({ apiKey: K_OAI }, { fetch: down, resolveHost: publicHost }),
    (e) => e.kind === "network" && !/10\.0\.0\.9|secret/.test(e.message),
  );
  const slow = (url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)));
  // AbortSignal.timeout does not keep the event loop alive; a live socket does in production.
  const keepAlive = setTimeout(() => {}, 2000);
  await assert.rejects(
    () => live.fetchOpenAiModels({ apiKey: K_OAI }, { fetch: slow, resolveHost: publicHost, timeoutMs: 20 }),
    (e) => e.kind === "network" && /in time/.test(e.message),
  );
  clearTimeout(keepAlive);
});

test("no API key is an auth error and nothing is sent", async () => {
  const f = fakeFetch(() => ({ body: {} }));
  await assert.rejects(() => live.fetchAnthropicModels({}, { fetch: f }), (e) => e.kind === "auth");
  await assert.rejects(() => live.fetchOpenAiModels({ apiKey: "  " }, { fetch: f }), (e) => e.kind === "auth");
  assert.equal(f.calls.length, 0);
});

/* ─── URL guard ─────────────────────────────────────────────── */

const reject = async (url, deps = {}) => {
  try {
    await guard.assertSafeBaseUrl(url, { resolveHost: publicHost, ...deps });
  } catch (e) {
    assert.ok(e instanceof ProviderError, `${url}: ${e}`);
    assert.equal(e.code, "BASE_URL_REJECTED", `${url}: ${e.message}`);
    return e.message;
  }
  assert.fail(`${url} should have been rejected`);
};

test("only https base URLs are accepted", async () => {
  await reject("http://api.example.com/v1");
  await reject("ftp://api.example.com");
  await reject("//api.example.com");
  await reject("not a url");
  assert.equal(await guard.assertSafeBaseUrl("https://api.example.com/v1/", { resolveHost: publicHost }), "https://api.example.com/v1");
  assert.equal(await guard.assertSafeBaseUrl("https://api.example.com", { resolveHost: publicHost }), "https://api.example.com");
});

test("credentials, queries and fragments in a base URL are refused", async () => {
  await reject("https://user:pw@api.example.com/v1");
  await reject("https://api.example.com/v1?key=1");
  await reject("https://api.example.com/v1#frag");
});

test("loopback and link-local hosts are refused in every spelling", async () => {
  for (const host of [
    "127.0.0.1", "127.1.2.3", "0.0.0.0", "2130706433", "0x7f.1", "0177.0.0.1", "017700000001",
    "[::1]", "[::]", "[::ffff:127.0.0.1]", "[::ffff:7f00:1]", "[0:0:0:0:0:ffff:7f00:1]", "[::127.0.0.1]",
    "169.254.169.254", "169.254.0.1", "[fe80::1]", "[fe80::abcd:1234]", "[febf::1]", "[fd00:ec2::254]", "[::ffff:169.254.169.254]",
  ]) {
    await reject(`https://${host}/v1`);
  }
});

test("localhost and its spellings, internal suffixes, single-label hosts and compose service names are refused", async () => {
  for (const host of [
    "localhost", "LOCALHOST", "localhost.", "foo.localhost", "a.b.localhost",
    "phantom-agent", "phantom-updater", "phantom-tls-init", "phantom-browser", "xlog", "caldera", "mcp",
    "xlog.", "metadata.google.internal", "printer.local",
  ]) {
    await reject(`https://${host}/v1`);
  }
});

test("the MCP host and any extra blocked host are refused", async () => {
  await reject("https://mcp.corp.example.com/v1", { blockedHosts: ["mcp.corp.example.com"] });
  await reject("https://MCP.CORP.EXAMPLE.COM./v1", { blockedHosts: ["mcp.corp.example.com"] });
});

test("private ranges stay allowed, so corporate gateways work", async () => {
  for (const host of ["10.1.2.3", "172.16.0.5", "192.168.1.9", "[fc00::1]"]) {
    assert.ok(await guard.assertSafeBaseUrl(`https://${host}/v1`, { resolveHost: publicHost }), host);
  }
});

test("a name that resolves to a loopback or link-local address is refused at call time (DNS rebinding)", async () => {
  await reject("https://sneaky.example.com/v1", { resolveHost: async () => ["127.0.0.1"] });
  await reject("https://sneaky.example.com/v1", { resolveHost: async () => ["203.0.113.10", "169.254.169.254"] });
  await reject("https://sneaky.example.com/v1", { resolveHost: async () => ["::1"] });
  await reject("https://sneaky.example.com/v1", { resolveHost: async () => ["::ffff:10.0.0.1", "::ffff:127.0.0.1"] });
  await assert.rejects(
    () => guard.assertSafeBaseUrl("https://gone.example.com", { resolveHost: async () => { throw new Error("ENOTFOUND"); } }),
    (e) => e.kind === "network",
  );
});

test("a rejected base URL stops the fetchers before any request", async () => {
  const f = fakeFetch(() => ({ body: { data: [] } }));
  for (const baseUrl of ["http://api.example.com", "https://localhost/v1", "https://169.254.169.254/latest", "https://xlog/v1"]) {
    await assert.rejects(
      () => live.fetchAnthropicModels({ apiKey: K_ANT, baseUrl }, { fetch: f, resolveHost: publicHost }),
      (e) => e.code === "BASE_URL_REJECTED",
    );
    await assert.rejects(
      () => live.fetchOpenAiModels({ apiKey: K_OAI, baseUrl }, { fetch: f, resolveHost: publicHost }),
      (e) => e.code === "BASE_URL_REJECTED",
    );
  }
  assert.equal(f.calls.length, 0);
});

test("a bad base URL fails the refresh, is audited, and the curated rows still serve", async () => {
  const f = providers();
  const r = makeRegistry(f, clock());
  const entries = await r.list({ creds: { ...ALL, anthropic: { apiKey: K_ANT, baseUrl: "https://169.254.169.254" } } });
  assert.equal(byRef(entries, "anthropic/claude-opus-5-5").providerState, "offline");
  assert.match(byRef(entries, "anthropic/claude-opus-5-5").refreshError, /link-local/);
  assert.equal(f.calls.filter((c) => c.url.includes("169.254")).length, 0);
});

test("blockedAddressReason classifies addresses", () => {
  assert.equal(guard.blockedAddressReason("198.51.100.7"), null);
  assert.equal(guard.blockedAddressReason("2001:db8::1"), null);
  assert.match(guard.blockedAddressReason("127.0.0.1"), /loopback/);
  assert.match(guard.blockedAddressReason("169.254.1.1"), /link-local/);
  assert.match(guard.blockedAddressReason("::1"), /loopback/);
  assert.match(guard.blockedAddressReason("fe80::1"), /link-local/);
});

/* ─── Credentials ───────────────────────────────────────────── */

function storeFetch(instances) {
  return fakeFetch((url) => {
    const u = new URL(url);
    if (u.pathname === "/api/v1/providers") {
      const pid = u.searchParams.get("provider_id");
      const list = instances.filter((i) => i.provider_id === pid).map((i) => ({ id: i.id, provider_id: i.provider_id, config: i.config, secrets: { api_key: "***" } }));
      return { body: { instances: list } };
    }
    const m = u.pathname.match(/^\/api\/v1\/providers\/(.+)$/);
    const inst = instances.find((i) => i.id === decodeURIComponent(m[1]));
    return inst && u.searchParams.get("include_secrets") === "true" ? { body: { instance: inst } } : { status: 404, body: {} };
  });
}
const MCP = () => ({ base: "http://localhost:8080", token: "tok-fake" });

test("credentials: each provider's stored instance maps onto adapter credentials", async () => {
  creds.bustProviderCredsCache();
  const f = storeFetch([
    { id: "a1", provider_id: "anthropic", config: { base_url: "https://gw.example.com" }, secrets: { api_key: K_ANT } },
    { id: "o1", provider_id: "openai", config: { organization: "org-fake", project: "proj-fake" }, secrets: { api_key: K_OAI } },
    { id: "v1", provider_id: "vertex", config: { project_id: "p" }, secrets: { serviceAccountJson: '{"type":"service_account"}' } },
  ]);
  const deps = { fetch: f, mcp: MCP };
  assert.deepEqual(await creds.resolveProviderCreds("anthropic", deps), { apiKey: K_ANT, baseUrl: "https://gw.example.com" });
  assert.deepEqual(await creds.resolveProviderCreds("openai", deps), { apiKey: K_OAI, organization: "org-fake", project: "proj-fake" });
  assert.deepEqual(await creds.resolveProviderCreds("vertex", deps), { serviceAccountJson: '{"type":"service_account"}' });
  const detail = f.calls.find((c) => c.url.includes("/providers/a1"));
  assert.match(detail.url, /include_secrets=true$/);
  assert.equal(detail.init.headers.Authorization, "Bearer tok-fake");
});

test("credentials: cached for 30 seconds, then read again; bust drops the cache", async () => {
  creds.bustProviderCredsCache();
  const c = clock();
  const f = storeFetch([{ id: "a1", provider_id: "anthropic", config: {}, secrets: { api_key: K_ANT } }]);
  const deps = { fetch: f, mcp: MCP, now: c.now };
  await creds.resolveProviderCreds("anthropic", deps);
  await creds.resolveProviderCreds("anthropic", deps);
  assert.equal(f.calls.length, 2, "one list and one detail, then cached");
  c.advance(31_000);
  await creds.resolveProviderCreds("anthropic", deps);
  assert.equal(f.calls.length, 4);
  creds.bustProviderCredsCache("anthropic");
  await creds.resolveProviderCreds("anthropic", deps);
  assert.equal(f.calls.length, 6);
});

test("credentials: not configured means null; a transport failure is null, not a throw; the environment is never a fallback", async () => {
  creds.bustProviderCredsCache();
  const prior = process.env.ANTHROPIC_API_KEY;
  process.env.ANTHROPIC_API_KEY = K_ANT + "-ENV";
  try {
    const empty = storeFetch([]);
    assert.equal(await creds.resolveProviderCreds("anthropic", { fetch: empty, mcp: MCP }), null);
    creds.bustProviderCredsCache();
    const blank = storeFetch([{ id: "a1", provider_id: "anthropic", config: {}, secrets: { api_key: "   " } }]);
    assert.equal(await creds.resolveProviderCreds("anthropic", { fetch: blank, mcp: MCP }), null);
    creds.bustProviderCredsCache();
    const broken = async () => { throw new Error("connection refused"); };
    assert.equal(await creds.resolveProviderCreds("anthropic", { fetch: broken, mcp: MCP }), null);
    creds.bustProviderCredsCache();
    assert.equal(await creds.resolveProviderCreds("anthropic", { fetch: empty, mcp: () => null }), null);
  } finally {
    if (prior === undefined) delete process.env.ANTHROPIC_API_KEY;
    else process.env.ANTHROPIC_API_KEY = prior;
    creds.bustProviderCredsCache();
  }
});

/* ─── Verify (Gemini :countTokens) ──────────────────────────── */

const { verifyGeminiModel } = await import("../lib/providers/gemini/verify.ts");
const { isCredentialRoute } = await import("../lib/agent-scopes.ts");

// A service-account JSON shaped well enough to pass the placeholder guard, built
// at run time so no scanner mistakes the source for a real key.
function serviceAccountJson() {
  const pem = ["-----BEGIN", "PRIVATE", "KEY-----"].join(" ") + "\n" + "A".repeat(400) + "\n" + ["-----END", "PRIVATE", "KEY-----"].join(" ");
  return JSON.stringify({ type: "service_account", project_id: "proj-fake", private_key: pem, client_email: "svc@proj-fake.iam.gserviceaccount.com" });
}
const ACCESS_TOKEN = ["ya", "29." + "FAKE".repeat(4)].join("");
const fakeAuth = () => ({ getProjectId: async () => "proj-fake", getAccessToken: async () => ACCESS_TOKEN });

test("verify via the Gemini API: a token count, key in a header, no redirects", async () => {
  const f = fakeFetch(() => ({ body: { totalTokens: 3 } }));
  const r = await verifyGeminiModel({ apiKey: K_GEM }, "gemini-3.1-pro-preview", { fetch: f });
  assert.deepEqual({ ok: r.ok, via: r.via }, { ok: true, via: "gemini-api" });
  assert.match(f.calls[0].url, /\/models\/gemini-3\.1-pro-preview:countTokens$/);
  assert.ok(!f.calls[0].url.includes(K_GEM));
  assert.equal(f.calls[0].init.headers["x-goog-api-key"], K_GEM);
  assert.equal(f.calls[0].init.redirect, "manual");
  assert.ok(!r.message.includes(K_GEM));
});

test("verify via Vertex when only a service account exists: project, location and bearer token", async () => {
  const f = fakeFetch(() => ({ body: { totalTokens: 3 } }));
  const r = await verifyGeminiModel({ serviceAccountJson: serviceAccountJson() }, "gemini-2.5-flash", { fetch: f, createAuth: fakeAuth });
  assert.deepEqual({ ok: r.ok, via: r.via }, { ok: true, via: "vertex" });
  assert.equal(f.calls[0].url, "https://aiplatform.googleapis.com/v1/projects/proj-fake/locations/us-central1/publishers/google/models/gemini-2.5-flash:countTokens");
  assert.equal(f.calls[0].init.headers.Authorization, `Bearer ${ACCESS_TOKEN}`);
  const g3 = fakeFetch(() => ({ body: {} }));
  await verifyGeminiModel({ serviceAccountJson: serviceAccountJson() }, "gemini-3.7-flash", { fetch: g3, createAuth: fakeAuth });
  assert.match(g3.calls[0].url, /\/locations\/global\//, "Gemini 3 models use the global location");
});

test("verify falls back to Vertex when the API key is rejected and a service account exists", async () => {
  const f = fakeFetch((url) =>
    url.includes("generativelanguage")
      ? { status: 400, body: { error: { message: "API key not valid. Please pass a valid API key." } } }
      : { body: { totalTokens: 1 } });
  const r = await verifyGeminiModel({ apiKey: K_GEM, serviceAccountJson: serviceAccountJson() }, "gemini-2.5-pro", { fetch: f, createAuth: fakeAuth });
  assert.deepEqual({ ok: r.ok, via: r.via }, { ok: true, via: "vertex" });
  assert.equal(f.calls.length, 2);
});

test("verify reports a missing or disabled model without echoing bodies or keys", async () => {
  const missing = fakeFetch(() => ({ status: 404, body: { error: { message: `Publisher Model was not found ${K_GEM}` } } }));
  const r = await verifyGeminiModel({ apiKey: K_GEM }, "gemini-3.8-flash", { fetch: missing });
  assert.equal(r.ok, false);
  assert.match(r.message, /not found, or it is not enabled/);
  assert.ok(!r.message.includes(K_GEM));
  const html = fakeFetch(() => ({ status: 500, raw: "<html>internal-detail-9</html>", headers: { "content-type": "text/html" } }));
  const h = await verifyGeminiModel({ apiKey: K_GEM }, "gemini-3.8-flash", { fetch: html });
  assert.ok(!h.message.includes("internal-detail-9"));
  assert.match(h.message, /HTTP 500/);
});

test("verify never echoes a malformed service-account JSON, and refuses with no credentials", async () => {
  const f = fakeFetch(() => ({ body: {} }));
  const bad = await verifyGeminiModel({ serviceAccountJson: '{"type": "service_account", "private_key": "SECRET-MATERIAL" ' }, "gemini-2.5-pro", { fetch: f });
  assert.equal(bad.ok, false);
  assert.ok(!bad.message.includes("SECRET-MATERIAL"));
  const none = await verifyGeminiModel({}, "gemini-2.5-pro", { fetch: f });
  assert.equal(none.ok, false);
  assert.match(none.message, /Providers page/);
  assert.equal(f.calls.length, 0);
});

test("the verify route sits under the credential prefix, so API keys get a 403", () => {
  assert.equal(isCredentialRoute("/api/agent/providers/vertex/verify"), true);
  assert.equal(isCredentialRoute("/api/agent/models"), false);
});

/* ─── Source guards ─────────────────────────────────────────── */

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.ts$/.test(name)) yield full;
  }
}

test("registry modules read no environment, import no @/ alias and spawn nothing", () => {
  const dir = join(root, "lib", "providers", "registry");
  const files = [...walk(dir), join(root, "lib", "providers", "url-guard.ts")];
  assert.ok(files.length >= 9, `only ${files.length} files scanned`);
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    const rel = relative(root, file);
    assert.ok(!/process\.env/.test(text), `${rel} reads process.env`);
    assert.ok(!/from\s+["']@\//.test(text), `${rel} imports through @/`);
    assert.ok(!/child_process/.test(text), `${rel} mentions child_process`);
  }
});

test("only the credentials reader reads the environment, and only for the MCP address", () => {
  const text = readFileSync(join(root, "lib", "providers", "credentials.ts"), "utf8");
  const reads = [...text.matchAll(/process\.env\.([A-Z_]+)/g)].map((m) => m[1]).sort();
  assert.deepEqual([...new Set(reads)], ["MCP_TOKEN", "MCP_URL"]);
});

await run();
if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall tests passed");
