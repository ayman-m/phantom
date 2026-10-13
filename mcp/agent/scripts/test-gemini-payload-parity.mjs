#!/usr/bin/env node
/**
 * Gemini wire parity: the bytes sent to Gemini must not change.
 *
 * scripts/fixtures/gemini-parity/fixtures.json was recorded from the ORIGINAL
 * chat-route code (see record.mjs there: route.ts at commit f6c50edf, run in a
 * sandbox with stubbed fetch). This test replays every scenario three ways and
 * compares URL, method, headers and the exact request body string (plus the
 * auth/cache calls, retry sleeps, warnings and the result or thrown message):
 *
 *   (a) the moved functions in lib/providers/gemini (buildGeminiPayload +
 *       callGeminiGenerateContent), fed the legacy Gemini-shaped inputs;
 *   (b) the Gemini adapter, fed the equivalent provider-neutral ModelRequest;
 *   (c) the dispatch layer the route calls (lib/providers/dispatch.ts:
 *       callModel and summarizeText) with the real Gemini adapter underneath,
 *       fed the neutral request the route builds for each entry point
 *       (main turn, subagent, summarizer, /plan, budget summary), so the
 *       purpose -> "no provider" wording mapping and the summarizer's text
 *       join are covered, plus checks on the glue that stayed in the route.
 *       (Before the route moved onto callModel, this section lifted the
 *       route's old callGemini / callGeminiRaw / summarizeViaGemini
 *       wrappers by name; those functions are gone, and this replaces them.)
 *
 * Then it checks the adapter's response mapping, the retry helper, redaction
 * and error classification.
 *
 *   node scripts/test-gemini-payload-parity.mjs   (npm run test:gemini-payload-parity)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node
 * without it the test skips (the build type-checks the modules).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const fixtureDir = join(here, "fixtures", "gemini-parity");

const scenariosMod = await import("./fixtures/gemini-parity/scenarios.mjs");
const {
  FAKE_ACCESS_TOKEN, SYSTEM_TEXT, buildScenarios, legacyTools, neutralTools, runtimeConfigFor,
} = scenariosMod;

const { toGeminiSchema } = await import("../lib/providers/schema.ts");
const { buildGeminiPayload } = await import("../lib/providers/gemini/payload.ts");
const transport = await import("../lib/providers/gemini/transport.ts");
const adapterMod = await import("../lib/providers/gemini/adapter.ts");
const retry = await import("../lib/providers/retry.ts");
const errorsMod = await import("../lib/providers/errors.ts");
const { callGeminiGenerateContent, GEMINI_NO_PROVIDER_MESSAGES } = transport;

const fixtures = JSON.parse(readFileSync(join(fixtureDir, "fixtures.json"), "utf8"));
const byId = new Map(fixtures.scenarios.map((s) => [s.id, s]));
const scenarios = buildScenarios();

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.message).split("\n").join("\n     ")); }
}

/* ─── A world per scenario: stubs that record what the code did ─── */

function makeWorld(sc) {
  const state = { requests: [], authCalls: [], cacheCalls: [], sleeps: [], warns: [], promptModelArgs: [] };
  const queue = sc.responses.map((r) => structuredClone(r));
  const deps = {
    fetch: async (url, init) => {
      state.requests.push({ url, method: init.method, headers: { ...init.headers }, body: init.body });
      const next = queue.shift();
      if (!next) throw new Error("test: no scripted response left for this request");
      const text = next.text !== undefined ? next.text : JSON.stringify(next.body);
      return {
        ok: next.status < 400,
        status: next.status,
        text: async () => text,
        json: async () => (next.body !== undefined ? structuredClone(next.body) : JSON.parse(text)),
      };
    },
    createAuth: (opts) => {
      state.authCalls.push({
        hasCredentials: Boolean(opts.credentials),
        credentialsProjectId: opts.credentials ? opts.credentials.project_id : null,
        keyFile: opts.keyFile ?? null,
        scopes: opts.scopes,
      });
      return { getProjectId: async () => "adc-project", getAccessToken: async () => FAKE_ACCESS_TOKEN };
    },
    getSystemPromptCache: async (args) => {
      state.cacheCalls.push({ ...args });
      if (sc.cache === "throw") throw new Error("cache helper exploded");
      return sc.cache === "name" ? "cachedContents/parity-1" : null;
    },
    // vertexCacheEnabled is deliberately NOT injected: the default must read
    // process.env.PHANTOM_VERTEX_CACHE at call time.
    retry: { sleep: async (ms) => { state.sleeps.push(ms); }, random: () => 0.25 },
  };
  return { state, deps };
}

/** Run `fn` with the scenario's env and a console.warn capture. */
async function withEnvAndWarn(sc, state, fn) {
  const savedEnv = process.env.PHANTOM_VERTEX_CACHE;
  const savedWarn = console.warn;
  if (sc.env.PHANTOM_VERTEX_CACHE === undefined) delete process.env.PHANTOM_VERTEX_CACHE;
  else process.env.PHANTOM_VERTEX_CACHE = sc.env.PHANTOM_VERTEX_CACHE;
  console.warn = (...args) => { state.warns.push(args); };
  try {
    return await fn();
  } finally {
    console.warn = savedWarn;
    if (savedEnv === undefined) delete process.env.PHANTOM_VERTEX_CACHE;
    else process.env.PHANTOM_VERTEX_CACHE = savedEnv;
  }
}

async function observe(sc, run) {
  const world = makeWorld(sc);
  let result;
  try {
    const value = await withEnvAndWarn(sc, world.state, () => run(world.deps, world.state));
    result = { value };
  } catch (err) {
    result = { thrown: err.message };
  }
  return { state: world.state, result };
}

/** Compare one observed run against its recorded fixture, field by field. */
function compare(fx, obs, { checkValue }) {
  assert.equal(obs.state.requests.length, fx.requests.length, `request count (${obs.state.requests.length} vs ${fx.requests.length})`);
  fx.requests.forEach((want, i) => {
    const got = obs.state.requests[i];
    assert.equal(got.url, want.url, `request ${i} url`);
    assert.equal(got.method, want.method, `request ${i} method`);
    assert.deepEqual(got.headers, want.headers, `request ${i} headers`);
    if (got.body !== want.body) {
      let at = 0;
      while (at < got.body.length && got.body[at] === want.body[at]) at += 1;
      assert.fail(`request ${i} body differs at char ${at}\n  want: ...${want.body.slice(Math.max(0, at - 40), at + 80)}\n  got:  ...${got.body.slice(Math.max(0, at - 40), at + 80)}`);
    }
  });
  assert.deepEqual(obs.state.authCalls, fx.authCalls, "auth client calls");
  assert.deepEqual(obs.state.cacheCalls, fx.cacheCalls, "system-prompt cache calls");
  assert.deepEqual(obs.state.sleeps, fx.sleeps, "retry sleeps");
  assert.deepEqual(JSON.parse(JSON.stringify(obs.state.warns)), fx.warns, "console.warn calls");
  if (fx.result.thrown !== undefined) {
    assert.equal(obs.result.thrown, fx.result.thrown, "thrown message");
  } else {
    assert.equal(obs.result.thrown, undefined, `unexpected throw: ${obs.result.thrown}`);
    if (checkValue) assert.deepEqual(JSON.parse(JSON.stringify(obs.result.value)), fx.result.value, "returned JSON");
  }
}

/* ─── (a) the moved functions ───────────────────────────────── */

for (const sc of scenarios) {
  const fx = byId.get(sc.id);
  await test(`(a) moved functions: ${sc.id}`, async () => {
    assert.ok(fx, "no fixture recorded for this scenario");
    const obs = await observe(sc, (deps) => {
      const l = sc.legacy;
      const rc = runtimeConfigFor(sc.creds);
      if (l.entry === "summarize") {
        const payload = buildGeminiPayload({
          contents: [{ role: "user", parts: [{ text: l.userContent }] }], tools: [], systemText: l.systemText,
        });
        return callGeminiGenerateContent(payload, rc, l.model, GEMINI_NO_PROVIDER_MESSAGES.summarize, deps);
      }
      const payload = buildGeminiPayload({
        contents: structuredClone(l.contents),
        tools: legacyTools(l.toolsKind, toGeminiSchema),
        systemText: l.entry === "callGeminiRaw" ? l.systemText : SYSTEM_TEXT,
        thinking: l.thinking,
        forceToolUse: l.forceToolUse,
      });
      const message = l.entry === "callGeminiRaw" ? GEMINI_NO_PROVIDER_MESSAGES.subagent : GEMINI_NO_PROVIDER_MESSAGES.chat;
      return callGeminiGenerateContent(payload, rc, l.model, message, deps);
    });
    // summarize returns the model JSON here (the route wrapper joins the text); the
    // fixture holds the joined text, so only the other entries compare the value.
    compare(fx, obs, { checkValue: sc.legacy.entry !== "summarize" });
  });
}

/* ─── (b) the adapter, from neutral input ───────────────────── */

for (const sc of scenarios) {
  const fx = byId.get(sc.id);
  await test(`(b) adapter from neutral input: ${sc.id}`, async () => {
    const obs = await observe(sc, async (deps) => {
      const adapter = adapterMod.createGeminiAdapter(deps);
      const rc = runtimeConfigFor(sc.creds);
      const n = sc.neutral;
      const req = {
        ref: n.ref,
        system: n.system,
        messages: structuredClone(n.messages),
        tools: neutralTools(n.toolsKind),
        toolChoice: n.toolChoice,
        thinking: n.thinking,
        purpose: n.purpose,
      };
      const turn = await adapter.call(req, {
        creds: { apiKey: rc.GEMINI_API_KEY, serviceAccountJson: rc.GOOGLE_APPLICATION_CREDENTIALS },
        step: 0,
      });
      // The adapter returns a neutral turn built from the scripted OK response.
      assert.deepEqual(turn.raw, [{ text: "ok" }], "turn.raw is the native parts");
      assert.deepEqual(turn.text, ["ok"]);
      assert.equal(turn.finish, "stop");
      assert.deepEqual(turn.usage, {
        inputTotal: 12, cacheRead: 4, cacheWrite: 0, cacheWrite1h: 0, output: 3, reasoning: 0,
      });
      return null;
    });
    compare(fx, obs, { checkValue: false });
  });
}

/* ─── (c) the dispatch layer the route calls ───────────────── */

const dispatch = await import("../lib/providers/dispatch.ts");

function requestFor(sc, purposeOverride) {
  const n = sc.neutral;
  return {
    ref: n.ref,
    system: n.system,
    messages: structuredClone(n.messages),
    tools: neutralTools(n.toolsKind),
    toolChoice: n.toolChoice,
    thinking: n.thinking,
    purpose: purposeOverride ?? n.purpose,
  };
}

for (const sc of scenarios) {
  const fx = byId.get(sc.id);
  await test(`(c) dispatch: ${sc.id}`, async () => {
    const obs = await observe(sc, async (deps) => {
      const dispatchDeps = { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } };
      const rc = runtimeConfigFor(sc.creds);
      const opts = { creds: dispatch.credsFromRuntimeConfig(rc), step: 0 };
      if (sc.legacy.entry === "summarize") {
        const n = sc.neutral;
        // The route's summarizeViaModel: the summarizer's own system text and one user message.
        return dispatch.summarizeText(n.ref, n.system, n.messages[0].text, "summarize", opts, dispatchDeps);
      }
      const turn = await dispatch.callModel(requestFor(sc), opts, dispatchDeps);
      assert.deepEqual(turn.text, ["ok"]);
      return null;
    });
    compare(fx, obs, { checkValue: false });
    if (sc.legacy.entry === "summarize" && fx.result.thrown === undefined) {
      assert.equal(obs.result.value, "ok", "summarizeText returns the joined, trimmed text");
    }
  });
}

await test("(c) dispatch: /plan uses the summarizer wording and bytes", async () => {
  for (const id of ["summarize_apikey", "error_no_provider_summarize"]) {
    const sc = scenarios.find((s) => s.id === id);
    const fx = byId.get(id);
    const obs = await observe(sc, async (deps) => {
      const dispatchDeps = { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } };
      const n = sc.neutral;
      return dispatch.summarizeText(n.ref, n.system, n.messages[0].text, "plan",
        { creds: dispatch.credsFromRuntimeConfig(runtimeConfigFor(sc.creds)), step: 0 }, dispatchDeps);
    });
    compare(fx, obs, { checkValue: false });
  }
});

await test("(c) dispatch: the no-provider wording follows the purpose", async () => {
  const sc = scenarios.find((s) => s.id === "error_no_provider_main");
  const want = {
    chat: GEMINI_NO_PROVIDER_MESSAGES.chat,
    budget_summary: GEMINI_NO_PROVIDER_MESSAGES.chat,
    subagent: GEMINI_NO_PROVIDER_MESSAGES.subagent,
    summarize: GEMINI_NO_PROVIDER_MESSAGES.summarize,
    plan: GEMINI_NO_PROVIDER_MESSAGES.summarize,
  };
  for (const [purpose, message] of Object.entries(want)) {
    const obs = await observe(sc, (deps) =>
      dispatch.callModel(requestFor(sc, purpose), { creds: {}, step: 0 },
        { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } }));
    assert.equal(obs.result.thrown, message, `purpose ${purpose}`);
    assert.equal(obs.state.requests.length, 0);
  }
});

await test("(c) dispatch: budget summary (tool choice none) keeps the tool list empty on the wire", async () => {
  const sc = scenarios.find((s) => s.id === "budget_summary_empty_tools");
  // Same history, but the route now hands the whole catalog and says 'none'.
  const req = { ...requestFor(sc, "budget_summary"), tools: neutralTools("full"), toolChoice: "none" };
  const obs = await observe(sc, (deps) =>
    dispatch.callModel(req, { creds: dispatch.credsFromRuntimeConfig(runtimeConfigFor(sc.creds)), step: 4 },
      { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } }));
  compare(byId.get(sc.id), obs, { checkValue: false });
});

await test("(c) dispatch: a subagent scope that matches no tool sends tools: [] (choice none)", async () => {
  const sc = scenarios.find((s) => s.id === "subagent_apikey");
  const req = { ...requestFor(sc), tools: [], toolChoice: "none" };
  const obs = await observe(sc, (deps) =>
    dispatch.callModel(req, { creds: dispatch.credsFromRuntimeConfig(runtimeConfigFor(sc.creds)), step: 0 },
      { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } }));
  const body = JSON.parse(obs.state.requests[0].body);
  assert.deepEqual(body.tools, []);
  assert.deepEqual(Object.keys(body), ["contents", "tools", "systemInstruction"]);
  // What the old route sent for an empty scope: filterToolsForAgent dropped the empty group.
  const legacy = buildGeminiPayload({
    contents: structuredClone(sc.legacy.contents), tools: [], systemText: sc.legacy.systemText,
  });
  assert.equal(obs.state.requests[0].body, JSON.stringify(legacy));
});

await test("(c) dispatch: a resolved model reference names the same model the old route handed the prompt builder", async () => {
  // The route resolves "provider/model" through the registry now (see
  // test-default-model.mjs); what must not change is that a valid Gemini model
  // reaches the wire as the bare model id the fixtures recorded.
  const { resolveChatModel } = await import("../lib/providers/model-resolution.ts");
  const { createModelRegistry } = await import("../lib/providers/registry/registry.ts");
  const entries = await createModelRegistry({ publishFacts: false }).list({
    creds: { vertex: { serviceAccountJson: "{}" } }, includeRetired: true,
  });
  let checked = 0;
  for (const sc of scenarios) {
    const fx = byId.get(sc.id);
    if (sc.legacy.entry !== "callGemini" || !fx.systemPromptModelArgs.length) continue;
    const r = resolveChatModel({ header: `vertex/${sc.legacy.model}` }, entries);
    assert.ok(r.ok, `${sc.id}: ${r.ok ? "" : r.message}`);
    assert.deepEqual([r.ref.model], fx.systemPromptModelArgs, sc.id);
    assert.equal(r.ref.provider, "vertex");
    checked += 1;
  }
  assert.ok(checked > 0, "no scenario exercised the resolver");
});

await test("(c) dispatch: the context-guard estimate is the old tools JSON", () => {
  const ref = { provider: "vertex", model: "m" };
  assert.equal(
    dispatch.estimateToolsJson(ref, neutralTools("full")),
    JSON.stringify(legacyTools("full", toGeminiSchema)),
  );
});

await test("(c) dispatch: a provider with no stored credentials fails through PROVIDER_NOT_CONFIGURED", async () => {
  // OpenAI has an adapter now, so the failure is the missing stored instance, and the caller's Google credentials never stand in for it.
  const bad = { ...requestFor(scenarios[0]), ref: { provider: "openai", model: "gpt" } };
  await assert.rejects(dispatch.callModel(bad, { creds: { apiKey: "AIza-caller-google-key" } }, { resolveCreds: async () => null }), (e) => {
    assert.equal(e.name, "ProviderError");
    assert.equal(e.code, "PROVIDER_NOT_CONFIGURED");
    assert.match(e.message, /OpenAI/);
    return true;
  });
});

/* The glue that stayed in the route (read from source: the route cannot be imported). */
const routeSource = readFileSync(join(root, "app", "api", "chat", "route.ts"), "utf8");

await test("route glue: the route reaches models only through dispatch", () => {
  for (const gone of ["function callGemini", "function callGeminiRaw", "function summarizeViaGemini",
    "function resolveModelName", "callGeminiGenerateContent", "buildGeminiPayload", "GEMINI_NO_PROVIDER_MESSAGES"]) {
    assert.ok(!routeSource.includes(gone), `route.ts still mentions ${gone}`);
  }
  assert.ok(/from '@\/lib\/providers\/dispatch'/.test(routeSource));
  // Every request the route builds names its purpose.
  assert.ok(routeSource.includes("purpose: 'subagent'"), "subagent requests name their purpose");
  assert.ok(routeSource.includes("options.toolChoice === 'none' ? 'budget_summary' : 'chat'"), "main requests name their purpose");
  assert.ok(routeSource.includes("purpose: 'summarize' | 'plan' = 'summarize'"), "summaries name their purpose");
});

function liftFunction(name) {
  const m = new RegExp(`^(async )?function ${name}\\(`, "m").exec(routeSource);
  assert.ok(m, `route.ts has no top-level function ${name}`);
  const tail = routeSource.slice(m.index);
  const end = /^}$/m.exec(tail);
  assert.ok(end, `could not find the end of ${name}`);
  return tail.slice(0, end.index + 1);
}

/** summarizeViaModel, lifted from the route as it is now and run against the real dispatch. */
function liftedSummarize(deps) {
  const dispatchDeps = { adapters: { vertex: adapterMod.createGeminiAdapter(deps) } };
  const sandbox = {
    credsFromRuntimeConfig: dispatch.credsFromRuntimeConfig,
    // The route's helper (blocked hosts); the Vertex adapter under test has no base URL to guard.
    modelDispatchDeps: () => ({}),
    summarizeText: (ref, system, text, purpose, opts) =>
      dispatch.summarizeText(ref, system, text, purpose, opts, dispatchDeps),
  };
  vm.createContext(sandbox);
  return vm.runInContext(
    `${stripTypeScriptTypes(liftFunction("summarizeViaModel"))}\n;summarizeViaModel;`,
    sandbox,
    { filename: "route.ts (lifted summarizeViaModel)" },
  );
}

const vertexRef = (model) => ({ provider: "vertex", model });

await test("route glue: summarizeViaModel runs the summarize scenarios on the model reference it is handed", async () => {
  for (const id of ["summarize_apikey", "summarize_vertex", "error_no_provider_summarize"]) {
    const sc = scenarios.find((x) => x.id === id);
    const fx = byId.get(id);
    const n = sc.neutral;
    const obs = await observe(sc, (deps) => liftedSummarize(deps)(n.system, n.messages[0].text,
      runtimeConfigFor(sc.creds), vertexRef(sc.model)));
    compare(fx, obs, { checkValue: false });
    if (fx.result.thrown === undefined) assert.equal(obs.result.value, "ok", "returns the joined, trimmed text");
    // A different model changes only the model in the URL, never the body.
    if (fx.requests.length) {
      const other = await observe(sc, (deps) => liftedSummarize(deps)(n.system, n.messages[0].text,
        runtimeConfigFor(sc.creds), vertexRef("gemini-other-model")));
      assert.ok(decodeURIComponent(other.state.requests[0].url).includes("gemini-other-model"), other.state.requests[0].url.split("?")[0]);
      assert.equal(other.state.requests[0].body, fx.requests[0].body, "only the model in the URL changes");
    }
  }
});

await test("route glue: summarizeViaModel defaults to the summarize purpose and passes 'plan' through", async () => {
  const sc = scenarios.find((x) => x.id === "error_no_provider_summarize");
  const n = sc.neutral;
  for (const purpose of [undefined, "summarize", "plan"]) {
    const obs = await observe(sc, (deps) => liftedSummarize(deps)(n.system, n.messages[0].text, {}, vertexRef(sc.model), purpose));
    assert.equal(obs.result.thrown, GEMINI_NO_PROVIDER_MESSAGES.summarize, `purpose ${purpose}`);
  }
  // A real request, to see the purpose does not change the bytes either.
  const ok = scenarios.find((x) => x.id === "summarize_apikey");
  for (const purpose of ["summarize", "plan"]) {
    const obs = await observe(ok, (deps) => liftedSummarize(deps)(ok.neutral.system, ok.neutral.messages[0].text, runtimeConfigFor(ok.creds), vertexRef(ok.model), purpose));
    compare(byId.get(ok.id), obs, { checkValue: false });
  }
});

await test("route glue: subagent_create's spec renders identically sanitized or not", () => {
  const m = /^const SUBAGENT_CREATE_TOOL_SPEC: ToolSpec = \{[\s\S]*?^\};/m.exec(routeSource);
  assert.ok(m, "SUBAGENT_CREATE_TOOL_SPEC literal not found");
  const name = /^const SUBAGENT_CREATE_TOOL = .*;$/m.exec(routeSource);
  assert.ok(name, "SUBAGENT_CREATE_TOOL constant not found");
  const spec = vm.runInNewContext(`${name[0]}\n${stripTypeScriptTypes(m[0])}\n;SUBAGENT_CREATE_TOOL_SPEC`);
  const [decl] = adapterMod.geminiFunctionDeclarations([spec]);
  // The old route appended this declaration as written (name, description, parameters).
  assert.equal(
    JSON.stringify(decl),
    JSON.stringify({ name: spec.name, description: spec.description, parameters: spec.inputSchema }),
  );
});

/* ─── Fixture coverage ──────────────────────────────────────── */

await test("fixtures were recorded from the pinned original route", () => {
  assert.equal(fixtures.provenance.commit, "f6c50edf");
  assert.equal(fixtures.scenarios.length, scenarios.length);
});

await test("the scenario set covers every required request shape", () => {
  const bodies = (id) => byId.get(id).requests.map((r) => JSON.parse(r.body));
  const keys = (id, i = 0) => Object.keys(bodies(id)[i]);
  assert.deepEqual(keys("main_thinking_off_apikey"), ["contents", "tools", "systemInstruction"]);
  assert.deepEqual(keys("main_thinking_on_apikey"), ["contents", "tools", "systemInstruction", "generationConfig"]);
  assert.deepEqual(keys("main_force_tool_use_thinking_off"), ["contents", "tools", "systemInstruction", "toolConfig"]);
  assert.deepEqual(keys("main_force_tool_use_thinking_on"), ["contents", "tools", "systemInstruction", "generationConfig", "toolConfig"]);
  assert.deepEqual(bodies("budget_summary_empty_tools")[0].tools, []);
  assert.deepEqual(keys("vertex_cache_swap"), ["contents", "tools", "generationConfig", "cachedContent"]);
  const followup = JSON.stringify(bodies("main_followup_tool_results_directive")[0]);
  assert.ok(followup.includes("__system_stop_directive__"), "stop directive present");
  assert.ok(followup.includes("thoughtSignature"), "thought signature replayed");
  assert.equal(byId.get("apikey_invalid_falls_back_to_vertex").requests.length, 2);
  assert.deepEqual(byId.get("error_rate_limit_exhausted").sleeps, [2250, 4250, 8250, 16250, 32250]);
});

/* ─── Adapter behaviour that fixtures do not cover ──────────── */

await test("adapter request: no mutation of the caller's tools or messages", () => {
  const n = scenarios.find((s) => s.id === "main_followup_tool_results_directive").neutral;
  const req = {
    ref: n.ref, system: n.system, messages: structuredClone(n.messages), tools: neutralTools("full"),
    toolChoice: "auto", thinking: true, purpose: "chat",
  };
  const before = JSON.stringify(req);
  adapterMod.buildGeminiRequestPayload(req);
  assert.equal(JSON.stringify(req), before);
});

await test("adapter request: auto with no tools keeps an empty declaration list, none drops to []", () => {
  const base = { ref: { provider: "vertex", model: "m" }, system: "s", messages: [{ role: "user", text: "hi" }], thinking: false, purpose: "chat" };
  assert.deepEqual(
    adapterMod.buildGeminiRequestPayload({ ...base, tools: [], toolChoice: "auto" }).tools,
    [{ functionDeclarations: [] }],
  );
  assert.deepEqual(adapterMod.buildGeminiRequestPayload({ ...base, tools: neutralTools("scoped"), toolChoice: "none" }).tools, []);
});

const GEMINI_RESPONSE = {
  candidates: [{
    content: { role: "model", parts: [
      { text: "plan: call default_api.run", thought: true },
      { text: "Running it." },
      { functionCall: { name: "xsiam.run_xql_query", args: { query: "q" } } },
      { functionCall: { name: "jobs_list" } },
      { text: "" },
    ] },
    finishReason: "STOP",
  }],
  usageMetadata: { promptTokenCount: 100, cachedContentTokenCount: 40, candidatesTokenCount: 7, thoughtsTokenCount: 11 },
  responseId: "resp-1",
};

await test("adapter response: text, thinking, calls, ids, usage, leak flag, raw", () => {
  const turn = adapterMod.parseGeminiResponse(structuredClone(GEMINI_RESPONSE), { model: "gemini-x", step: 3 });
  assert.deepEqual(turn.text, ["Running it."]);
  assert.deepEqual(turn.thinking, ["plan: call default_api.run"]);
  assert.deepEqual(turn.toolCalls, [
    { id: "gem_3_0", name: "xsiam.run_xql_query", args: { query: "q" } },
    { id: "gem_3_1", name: "jobs_list", args: {} },
  ]);
  assert.equal(turn.finish, "tool_use");
  assert.equal(turn.finishDetail, "STOP");
  assert.deepEqual(turn.usage, { inputTotal: 100, cacheRead: 40, cacheWrite: 0, cacheWrite1h: 0, output: 18, reasoning: 11 });
  assert.equal(turn.leakedToolCallSuspected, true);
  assert.equal(turn.requestId, "resp-1");
  assert.equal(turn.provider, "vertex");
  assert.equal(turn.model, "gemini-x");
  assert.deepEqual(turn.raw, GEMINI_RESPONSE.candidates[0].content.parts);
});

await test("adapter response: billed output is answer tokens plus thinking tokens; reasoning stays the informational subset", () => {
  const u = (usageMetadata) => adapterMod.parseGeminiResponse({ candidates: [{ content: { parts: [{ text: "t" }] }, finishReason: "STOP" }], usageMetadata }, { model: "m", step: 0 }).usage;
  assert.deepEqual(u({ promptTokenCount: 10, candidatesTokenCount: 5, thoughtsTokenCount: 200 }), { inputTotal: 10, cacheRead: 0, cacheWrite: 0, cacheWrite1h: 0, output: 205, reasoning: 200 });
  // A model that does not think reports no thoughtsTokenCount: output is unchanged.
  assert.equal(u({ promptTokenCount: 10, candidatesTokenCount: 5 }).output, 5);
  // Thinking that used the whole budget leaves no answer tokens at all.
  assert.equal(u({ promptTokenCount: 10, thoughtsTokenCount: 64 }).output, 64);
});

await test("adapter response: the leak flag needs a thought part carrying default_api", () => {
  const plain = { candidates: [{ content: { parts: [{ text: "default_api in an answer", thought: false }] }, finishReason: "STOP" }] };
  assert.equal(adapterMod.parseGeminiResponse(plain, { model: "m", step: 0 }).leakedToolCallSuspected, false);
});

await test("adapter response: finish reasons and missing usage", () => {
  const fin = (finishReason, parts = [{ text: "t" }]) =>
    adapterMod.parseGeminiResponse({ candidates: [{ content: { parts }, finishReason }] }, { model: "m", step: 0 });
  assert.equal(fin("STOP").finish, "stop");
  assert.equal(fin("MAX_TOKENS").finish, "max_tokens");
  assert.equal(fin("SAFETY").finish, "safety");
  assert.equal(fin("RECITATION").finish, "recitation");
  assert.equal(fin("OTHER").finish, "other");
  assert.equal(fin("OTHER").finishDetail, "OTHER");
  assert.equal(fin(undefined).finish, "other");
  assert.equal(fin("STOP", [{ functionCall: { name: "x" } }]).finish, "tool_use");
  assert.equal(fin("STOP").usage, null);
  const empty = adapterMod.parseGeminiResponse({}, { model: "m", step: 0 });
  assert.deepEqual([empty.text, empty.toolCalls, empty.raw], [[], [], []]);
});

await test("adapter: listModels is empty and testConnection points at the existing route", async () => {
  const a = adapterMod.createGeminiAdapter();
  assert.equal(a.id, "vertex");
  assert.deepEqual(await a.listModels({}, new AbortController().signal), []);
  const t = await a.testConnection({});
  assert.equal(t.ok, false);
  assert.match(t.message, /providers\/vertex\/test/);
});

/* ─── Retry helper ──────────────────────────────────────────── */

await test("withProviderRetry: Retry-After beats a smaller backoff, non-retryable errors throw at once", async () => {
  const sleeps = [];
  let calls = 0;
  const value = await retry.withProviderRetry(
    async () => { calls += 1; if (calls < 3) throw new Error("slow down"); return "done"; },
    () => ({ retryable: true, retryAfterMs: 5000 }),
    { maxRetries: 3, initialDelayMs: 100, backoffFactor: 2, jitterMs: 10, label: "x", reason: "hit 429" },
    { sleep: async (ms) => { sleeps.push(ms); }, random: () => 0, warn: () => {} },
  );
  assert.equal(value, "done");
  assert.deepEqual(sleeps, [5000, 5000]);
  let n = 0;
  await assert.rejects(
    retry.withProviderRetry(async () => { n += 1; throw new Error("bad"); }, () => ({ retryable: false }),
      { maxRetries: 3, initialDelayMs: 1, backoffFactor: 2, jitterMs: 1, label: "x", reason: "r" }, { sleep: async () => {} }),
    /bad/,
  );
  assert.equal(n, 1);
});

await test("Gemini retry policy matches the old withRateLimitRetry strings", () => {
  for (const msg of ["Gemini API error: 429 x", "RESOURCE_EXHAUSTED", "Resource exhausted", "Rate Limit hit"]) {
    assert.equal(retry.classifyGeminiRateLimit(new Error(msg)).retryable, true, msg);
  }
  for (const msg of ["Gemini API error: 500 boom", "Vertex AI error: 503", "timeout"]) {
    assert.equal(retry.classifyGeminiRateLimit(new Error(msg)).retryable, false, msg);
  }
});

/* ─── Errors ────────────────────────────────────────────────── */

await test("redactSecrets strips provider keys, key= params and bearer tokens", () => {
  const { redactSecrets, ProviderError } = errorsMod;
  // Credential-shaped strings are assembled at run time so no scanner sees one in the source.
  const googleKey = ["AI", "zaSy", "FAKE".repeat(8)].join("");
  const anthropicKey = ["sk", "ant", "api03", "FAKE".repeat(4)].join("-");
  const openaiKey = ["sk", "proj-" + "FAKE".repeat(5)].join("-");
  const text = `url ?key=${googleKey} and ${anthropicKey} and ${openaiKey} ` +
    "and Authorization: Bearer fake.token-value~1 and api_key=hunter2hunter2";
  const out = redactSecrets(text);
  for (const leaked of ["AIzaSyFAKE", "sk-ant-api03", "sk-proj-FAKE", "fake.token-value", "hunter2"]) {
    assert.ok(!out.includes(leaked), `${leaked} survived: ${out}`);
  }
  const err = new ProviderError({ kind: "auth", message: "bad key=SECRETVALUE" });
  assert.ok(!err.message.includes("SECRETVALUE"));
  assert.equal(err.name, "ProviderError");
  assert.equal(err.retryable, false);
});

await test("classifyGeminiError maps statuses and redacts", () => {
  const c = adapterMod.classifyGeminiError;
  assert.equal(c(new Error("Gemini API error: 429 RESOURCE_EXHAUSTED")).kind, "rate_limit");
  assert.equal(c(new Error("Gemini API error: 429 RESOURCE_EXHAUSTED")).retryable, true);
  assert.equal(c(new Error("Gemini API error: 400 API key not valid")).kind, "auth");
  assert.equal(c(new Error("Vertex AI error: 403 denied")).kind, "permission");
  assert.equal(c(new Error("Vertex AI error: 404 no model")).kind, "model_not_found");
  assert.equal(c(new Error("Vertex AI error: 400 token count exceeds the maximum")).kind, "context_exceeded");
  assert.equal(c(new Error("Vertex AI error: 500 x")).kind, "unavailable");
  assert.equal(c(new Error("fetch failed")).kind, "network");
  const googleKey = ["AI", "zaSy", "FAKE".repeat(8)].join("");
  assert.equal(c(new Error(`Gemini API error: 400 for ?key=${googleKey}`)).message.includes("AIza"), false);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
