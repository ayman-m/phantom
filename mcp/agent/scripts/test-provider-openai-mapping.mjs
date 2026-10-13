#!/usr/bin/env node
/**
 * OpenAI Responses mapping (lib/providers/openai/{payload,adapter}.ts,
 * lib/providers/schema.ts toPortableSchema, lib/providers/dispatch.ts): input
 * items and their order, stateless replay of reasoning items, function_call
 * and function_call_output pairing, directives, reasoning effort per model,
 * tool_choice rules, max_output_tokens, prompt_cache_key, the absence of
 * sampling parameters, tool-name encoding under the 64-character cap, finish
 * reasons, refusals, adapter events and the credential rule at dispatch.
 *
 *   node scripts/test-provider-openai-mapping.mjs   (npm run test:provider-openai-mapping)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node
 * without it the test skips (the build type-checks the modules).
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const payload = await import("../lib/providers/openai/payload.ts");
const { createOpenAiAdapter, toAssistantTurn, mapResponseStatus } = await import("../lib/providers/openai/adapter.ts");
const { readOpenAiStream } = await import("../lib/providers/openai/stream.ts");
const { lookupModelFacts } = await import("../lib/providers/registry/lookup.ts");
const dispatch = await import("../lib/providers/dispatch.ts");
const { ProviderError } = await import("../lib/providers/errors.ts");
const { buildToolNameCodec } = await import("../lib/providers/tool-names.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "openai-sse");
const fixtureBytes = (name) => readFileSync(join(fixtureDir, name));

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

const CAP = 65_536;
const SCHEMA = { type: "object", properties: { query: { type: "string" } }, required: ["query"] };
const tool = (name, description = "d", inputSchema = SCHEMA) => ({ name, description, inputSchema });
const TOOLS = [tool("xsiam.run_xql_query", "Run XQL"), tool("memory_search", "Search memory")];

function request(over = {}) {
  return {
    ref: { provider: "openai", model: "gpt-6-sol" },
    system: "You are Phantom.",
    messages: [{ role: "user", text: "hello" }],
    tools: TOOLS,
    toolChoice: "auto",
    thinking: true,
    purpose: "chat",
    ...over,
  };
}
const build = (over, model = "gpt-6-sol", rulesOverride, replay) =>
  payload.buildOpenAiRequest(request({ ...over, ref: { provider: "openai", model } }), {
    rules: rulesOverride === undefined ? lookupModelFacts(`openai/${model}`) : rulesOverride,
    maxTokensCap: CAP,
    replay,
  });

const sha256 = (s) => createHash("sha256").update(s).digest("hex");

/* ─── Envelope ─────────────────────────────────────────────── */

await test("store is false, the body streams, the system prompt is `instructions`, and the model is set", () => {
  const { body } = build();
  assert.equal(body.store, false);
  assert.equal(body.stream, true);
  assert.equal(body.model, "gpt-6-sol");
  assert.equal(body.instructions, "You are Phantom.");
  assert.equal("system" in body, false);
  assert.equal("previous_response_id" in body, false, "nothing is chained server side");
});

await test("a blank system prompt sends no `instructions`", () => {
  assert.equal("instructions" in build({ system: "  \n " }).body, false);
});

await test("temperature, top_p, truncation and service_tier are never sent, for any model, thinking state or tool choice", () => {
  for (const model of ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-unknown"]) {
    for (const thinking of [true, false]) {
      for (const toolChoice of ["auto", "required", "none"]) {
        const { body } = build({ thinking, toolChoice }, model);
        for (const key of ["temperature", "top_p", "truncation", "service_tier", "top_logprobs"]) {
          assert.equal(key in body, false, `${model} ${key}`);
        }
      }
    }
  }
});

await test("max_output_tokens is min(model maximum, 65536); a model without a stated maximum gets the conservative 32000", () => {
  assert.equal(build().body.max_output_tokens, 65_536, "128K model is capped");
  assert.equal(build({}, "gpt-5.6-terra").body.max_output_tokens, payload.UNKNOWN_MODEL_MAX_TOKENS, "maxOutput not stated");
  assert.equal(build({}, "gpt-not-in-registry", null).body.max_output_tokens, 32_000);
  const small = { maxOutput: 4096, forcedToolChoice: false, thinking: { on: "none", offMode: "omit" } };
  assert.equal(build({}, "x", small).body.max_output_tokens, 4096);
});

await test("prompt_cache_key is the SHA-256 of cacheKey, never the raw value; absent when there is no cacheKey", () => {
  const { body } = build({ cacheKey: "session-1234" });
  assert.equal(body.prompt_cache_key, sha256("session-1234"));
  assert.match(body.prompt_cache_key, /^[0-9a-f]{64}$/);
  assert.ok(!JSON.stringify(body).includes("session-1234"));
  assert.equal("prompt_cache_key" in build().body, false);
  assert.equal("prompt_cache_key" in build({ cacheKey: "" }).body, false);
});

/* ─── Input items ──────────────────────────────────────────── */

await test("history text becomes `message` items with plain string content; blank text is dropped", () => {
  const { body } = build({
    messages: [
      { role: "user", text: "one" },
      { role: "assistant", text: "a1" },
      { role: "user", text: "   " },
      { role: "user", text: "two" },
    ],
  });
  assert.deepEqual(body.input, [
    { type: "message", role: "user", content: "one" },
    { type: "message", role: "assistant", content: "a1" },
    { type: "message", role: "user", content: "two" },
  ]);
});

await test("no usable message at all sends one placeholder user message, never an empty input", () => {
  const { body } = build({ messages: [{ role: "user", text: "  " }] });
  assert.deepEqual(body.input, [{ type: "message", role: "user", content: payload.PLACEHOLDER_EMPTY_USER }]);
});

const RAW = [
  { id: "rs_1", type: "reasoning", summary: [{ type: "summary_text", text: "plan" }], encrypted_content: "ENC_1" },
  { id: "msg_1", type: "message", status: "completed", role: "assistant", phase: "commentary", content: [{ type: "output_text", text: "Looking.", annotations: [] }] },
  { id: "fc_1", type: "function_call", status: "completed", call_id: "call_1", name: "xsiam__run_xql_query", arguments: '{"query":"q"}' },
  { id: "fc_2", type: "function_call", status: "completed", call_id: "call_2", name: "memory_search", arguments: '{"query":"m"}' },
];
const turnOf = (raw) => ({ provider: "openai", model: "gpt-6-sol", text: [], thinking: [], toolCalls: [], finish: "tool_use", usage: null, leakedToolCallSuspected: false, raw });

await test("an in-loop turn is replayed verbatim and in order, then outputs in call order, then directives", () => {
  const { body } = build({
    messages: [
      { role: "user", text: "go" },
      { role: "assistant_turn", turn: turnOf(RAW) },
      {
        role: "tool_results",
        items: [
          { kind: "result", callId: "call_1", name: "xsiam.run_xql_query", payload: { result: { rows: 3 } } },
          { kind: "directive", text: "Stop calling tools." },
          { kind: "result", callId: "call_2", name: "memory_search", payload: { error: "boom" } },
        ],
      },
    ],
  });
  assert.deepEqual(body.input.slice(0, 5), [{ type: "message", role: "user", content: "go" }, ...RAW]);
  assert.deepEqual(body.input.slice(5), [
    { type: "function_call_output", call_id: "call_1", output: '{"result":{"rows":3}}' },
    { type: "function_call_output", call_id: "call_2", output: '{"error":"boom"}' },
    { type: "message", role: "user", content: "Stop calling tools." },
  ]);
  for (const item of body.input.slice(1, 5)) assert.ok(RAW.some((r) => JSON.stringify(r) === JSON.stringify(item)), "byte-identical replay");
});

await test("replay keeps encrypted_content, phase, ids and status untouched", () => {
  const items = payload.replayItems(RAW);
  assert.deepEqual(items, RAW);
  assert.notEqual(items[0], RAW[0], "copies, not the originals");
  assert.equal(items[0].encrypted_content, "ENC_1");
  assert.equal(items[1].phase, "commentary");
});

await test("a reasoning item without encrypted_content is dropped from the replay; one with it stays", () => {
  const items = payload.replayItems([
    { id: "rs_a", type: "reasoning", summary: [] },
    { id: "rs_b", type: "reasoning", summary: [], encrypted_content: "" },
    { id: "rs_c", type: "reasoning", summary: [], encrypted_content: "X" },
    RAW[2],
  ]);
  assert.deepEqual(items.map((i) => i.id), ["rs_c", "fc_1"]);
});

await test("a message with no text and no refusal is dropped; a refusal-only message stays", () => {
  const items = payload.replayItems([
    { id: "m1", type: "message", role: "assistant", content: [] },
    { id: "m2", type: "message", role: "assistant", content: [{ type: "output_text", text: "  " }] },
    { id: "m3", type: "message", role: "assistant", content: [{ type: "refusal", refusal: "no" }] },
    { id: "m4", type: "message", role: "assistant", content: [{ type: "output_text", text: "ok" }] },
  ]);
  assert.deepEqual(items.map((i) => i.id), ["m3", "m4"]);
});

await test("stripIds (off by default) removes every id from the replay, nothing else", () => {
  const items = payload.replayItems(RAW, { stripIds: true });
  assert.ok(items.every((i) => !("id" in i)));
  assert.equal(items[0].encrypted_content, "ENC_1");
  assert.equal(items[2].call_id, "call_1");
  assert.deepEqual(build({ messages: [{ role: "assistant_turn", turn: turnOf(RAW) }] }, "gpt-6-sol", undefined, { stripIds: true }).body.input.map((i) => "id" in i), [false, false, false, false]);
});

await test("a raw payload that is not an item list replays as nothing (no crash)", () => {
  for (const raw of [undefined, null, "x", {}, [null, 3, { noType: true }]]) assert.deepEqual(payload.replayItems(raw), []);
});

await test("a directive-only tool_results message is a single user message", () => {
  const { body } = build({ messages: [{ role: "user", text: "q" }, { role: "tool_results", items: [{ kind: "directive", text: "Wrap up." }] }] });
  assert.deepEqual(body.input.slice(1), [{ type: "message", role: "user", content: "Wrap up." }]);
});

/* ─── Tools ────────────────────────────────────────────────── */

await test("tools are function tools with wire names, strict:false, portable schemas, tool_choice auto and parallel calls on", () => {
  const { body } = build();
  assert.equal(body.tool_choice, "auto");
  assert.equal(body.parallel_tool_calls, true);
  assert.deepEqual(body.tools.map((t) => [t.type, t.name, t.strict]), [
    ["function", "xsiam__run_xql_query", false],
    ["function", "memory_search", false],
  ]);
  assert.deepEqual(body.tools[0].parameters, SCHEMA);
  assert.equal(body.tools[0].description, "Run XQL");
  assert.ok(body.tools.every((t) => !("function" in t)), "internally tagged: no nested function object");
});

await test("no tools: none of tools, tool_choice and parallel_tool_calls is sent, whatever the choice", () => {
  for (const toolChoice of ["auto", "required", "none"]) {
    const { body, events } = build({ tools: [], toolChoice });
    for (const key of ["tools", "tool_choice", "parallel_tool_calls"]) assert.equal(key in body, false, `${toolChoice} ${key}`);
    assert.deepEqual(events, [], "no downgrade event without tools");
  }
});

await test("tool_choice: none keeps the tools; required is sent when the model allows it", () => {
  const none = build({ toolChoice: "none" }).body;
  assert.equal(none.tool_choice, "none");
  assert.equal(none.tools.length, 2, "history may hold tool turns, so the tools stay");
  const required = build({ toolChoice: "required" });
  assert.equal(required.body.tool_choice, "required");
  assert.deepEqual(required.events, []);
});

await test("tool_choice required is downgraded to auto, with an event, for a model that is not known to allow it", () => {
  const { body, events } = build({ toolChoice: "required" }, "gpt-unknown", null);
  assert.equal(body.tool_choice, "auto");
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "tool_choice_downgraded");
  assert.deepEqual(events[0].data, { model: "gpt-unknown", requested: "required", sent: "auto" });
});

await test("a dotted MCP name is encoded and decoded; an alias pair collapses to the flat name", () => {
  const dup = tool("memory_search", "Same", SCHEMA);
  const dotted = tool("memory.search", "Same", SCHEMA);
  const { body, codec } = build({ tools: [dotted, dup, tool("a.b.c", "x")] });
  assert.deepEqual(body.tools.map((t) => t.name), ["memory_search", "a__b__c"]);
  assert.equal(codec.decode("a__b__c"), "a.b.c");
  assert.equal(codec.decode("memory_search"), "memory_search");
  assert.equal(codec.decode("never_advertised"), undefined, "a model cannot call an un-advertised tool");
});

await test("a name over 64 characters gets a sha1 suffix and round-trips; every wire name stays within the rules", () => {
  const long = "connector." + "very_long_tool_name_segment_".repeat(4) + "end";
  assert.ok(long.length > 64);
  const { body, codec } = build({ tools: [tool(long), tool(long + "2")] });
  for (const t of body.tools) {
    assert.match(t.name, /^[A-Za-z0-9_-]{1,64}$/);
    assert.ok(t.name.length <= 64);
  }
  assert.notEqual(body.tools[0].name, body.tools[1].name, "the suffix keeps long siblings apart");
  assert.equal(codec.decode(body.tools[0].name), long);
  assert.equal(codec.decode(body.tools[1].name), long + "2");
  assert.equal(codec.encode(long), body.tools[0].name);
});

await test("the 64-character codec is the one the adapter uses for its token estimate", () => {
  const adapter = createOpenAiAdapter();
  const estimate = adapter.estimateToolsPayload(TOOLS);
  assert.deepEqual(estimate.map((t) => t.name), ["xsiam__run_xql_query", "memory_search"]);
  assert.deepEqual(estimate, payload.openAiToolDefinitions(buildToolNameCodec(TOOLS, "openai").tools));
});

/* ─── Reasoning ────────────────────────────────────────────── */

await test("thinking on: the registry's default effort plus a summary, and encrypted reasoning is requested", () => {
  for (const [model, effort] of [["gpt-6-sol", "medium"], ["gpt-6-astra", "medium"], ["gpt-6.1-sol", "medium"], ["gpt-6-luna", "medium"], ["gpt-5.6-sol", "medium"]]) {
    const { body } = build({ thinking: true }, model);
    assert.deepEqual(body.reasoning, { summary: "auto", effort }, model);
    assert.deepEqual(body.include, ["reasoning.encrypted_content"], model);
  }
});

await test("thinking off follows the model's off mode: none where it exists, otherwise the lowest listed effort, otherwise nothing", () => {
  // gpt-6-sol and gpt-6-luna have a "none" level.
  assert.deepEqual(build({ thinking: false }, "gpt-6-sol").body.reasoning, { effort: "none" });
  assert.deepEqual(build({ thinking: false }, "gpt-6-luna").body.reasoning, { effort: "none" });
  // gpt-6-astra has no "none"; gpt-6.1-sol has neither "none" nor "minimal": never send what they lack.
  assert.deepEqual(build({ thinking: false }, "gpt-6-astra").body.reasoning, { effort: "low" });
  assert.deepEqual(build({ thinking: false }, "gpt-6.1-sol").body.reasoning, { effort: "low" });
  for (const model of ["gpt-6-astra", "gpt-6.1-sol"]) {
    const facts = lookupModelFacts(`openai/${model}`);
    assert.ok(!facts.thinking.efforts.includes("none"), `${model} lists no none level`);
    assert.ok(!facts.thinking.efforts.includes("minimal"), `${model} lists no minimal level`);
  }
  // Off mode "omit": no reasoning object, but the model may still reason, so encrypted reasoning is requested.
  const omit = build({ thinking: false }, "gpt-5.6-sol").body;
  assert.equal("reasoning" in omit, false);
  assert.deepEqual(omit.include, ["reasoning.encrypted_content"]);
});

await test("the effort sent is always one the registry lists for the model (or none where offMode says so)", () => {
  for (const model of ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"]) {
    const facts = lookupModelFacts(`openai/${model}`);
    for (const thinking of [true, false]) {
      const effort = build({ thinking }, model).body.reasoning?.effort;
      if (effort !== undefined) assert.ok(facts.thinking.efforts.includes(effort), `${model} thinking=${thinking} sent ${effort}`);
    }
  }
});

await test("a model without reasoning rules gets neither `reasoning` nor `include`", () => {
  for (const thinking of [true, false]) {
    const { body } = build({ thinking }, "gpt-unknown", null);
    assert.equal("reasoning" in body, false);
    assert.equal("include" in body, false);
  }
});

await test("a default effort the model does not list is not sent (the summary still is)", () => {
  const rules = { maxOutput: 1000, forcedToolChoice: true, thinking: { on: "reasoning", offMode: "omit", efforts: ["low", "high"], defaultEffort: "medium" } };
  assert.deepEqual(build({ thinking: true }, "x", rules).body.reasoning, { summary: "auto" });
  const noDefault = { ...rules, thinking: { on: "reasoning", offMode: "omit" } };
  assert.deepEqual(build({ thinking: true }, "x", noDefault).body.reasoning, { summary: "auto" });
});

/* ─── Response -> neutral turn ─────────────────────────────── */

const assembled = (name) => readOpenAiStream(new ReadableStream({ start(c) { c.enqueue(new Uint8Array(fixtureBytes(name))); c.close(); } }));
const decode = (wire) => ({ xsiam__run_xql_query: "xsiam.run_xql_query", memory_search: "memory_search" })[wire];

await test("tool-call: text, thinking summary, decoded tool call, usage, raw items and the request id", async () => {
  const events = [];
  const turn = toAssistantTurn(await assembled("tool-call.sse"), { model: "gpt-6-sol", decodeName: decode, requestId: "req_9", onEvent: (e) => events.push(e) });
  assert.equal(turn.provider, "openai");
  assert.deepEqual(turn.thinking, ["Need the open ports first."]);
  assert.deepEqual(turn.text, []);
  assert.deepEqual(turn.toolCalls, [{ id: "call_abc", name: "xsiam.run_xql_query", args: { query: "dataset = x | limit 1" } }]);
  assert.equal(turn.finish, "tool_use");
  assert.equal(turn.finishDetail, "completed");
  assert.equal(turn.requestId, "req_9");
  assert.equal(turn.leakedToolCallSuspected, false);
  assert.deepEqual(turn.usage, { inputTotal: 1200, cacheRead: 1024, cacheWrite: 0, cacheWrite1h: 0, output: 140, reasoning: 90 });
  assert.deepEqual(turn.raw.map((i) => i.type), ["reasoning", "function_call"]);
  assert.equal(turn.raw[0].encrypted_content, "ENC_BLOB_1");
  assert.deepEqual(events, []);
});

await test("text-only completes as a stop", async () => {
  const turn = toAssistantTurn(await assembled("text-only.sse"), { model: "gpt-6-sol", decodeName: decode });
  assert.deepEqual(turn.text, ["Scan ready — 3 hosts."]);
  assert.equal(turn.finish, "stop");
  assert.equal("requestId" in turn, false);
});

await test("parallel calls come back in order, each with its own call id", async () => {
  const turn = toAssistantTurn(await assembled("parallel-calls-no-output.sse"), { model: "gpt-6-sol", decodeName: decode });
  assert.deepEqual(turn.toolCalls.map((c) => [c.id, c.args]), [["call_a", { query: "kerberos" }], ["call_b", {}]]);
  assert.deepEqual(turn.text, ["Checking two things."]);
});

await test("incomplete at max_output_tokens: finish max_tokens, the cut-off call is gone from toolCalls AND raw, and an event says so", async () => {
  const events = [];
  const turn = toAssistantTurn(await assembled("incomplete-truncated-call.sse"), { model: "gpt-6-sol", decodeName: decode, onEvent: (e) => events.push(e) });
  assert.equal(turn.finish, "max_tokens");
  assert.equal(turn.finishDetail, "incomplete:max_output_tokens");
  assert.deepEqual(turn.toolCalls, []);
  assert.ok(turn.raw.every((i) => i.type !== "function_call"), "an unanswerable call is never replayed");
  assert.deepEqual(events.map((e) => [e.type, e.data]), [["tool_call_truncated", { name: "xsiam__run_xql_query" }]]);
});

await test("a refusal sets finish refusal, shows the model's own words as the reply, and raises a refusal event", async () => {
  const events = [];
  const turn = toAssistantTurn(await assembled("refusal.sse"), { model: "gpt-6-sol", decodeName: decode, onEvent: (e) => events.push(e) });
  assert.equal(turn.finish, "refusal");
  assert.deepEqual(turn.text, ["I can't help with that request."]);
  assert.deepEqual(events.map((e) => e.type), ["refusal"]);
  assert.deepEqual(events[0].data, { chars: "I can't help with that request.".length });
});

await test("an unknown tool name is kept as the model wrote it and reported", () => {
  const events = [];
  const turn = toAssistantTurn(
    { status: "completed", usage: {}, truncatedToolCalls: [], items: [{ type: "function_call", call_id: "c1", name: "made_up", arguments: "{}" }] },
    { model: "gpt-6-sol", decodeName: decode, onEvent: (e) => events.push(e) },
  );
  assert.equal(turn.toolCalls[0].name, "made_up");
  assert.deepEqual(events.map((e) => [e.type, e.data]), [["unknown_tool_name", { name: "made_up" }]]);
  assert.equal(turn.usage, null, "empty usage is null");
});

await test("a call without call_id falls back to the item id", () => {
  const turn = toAssistantTurn(
    { status: "completed", usage: {}, truncatedToolCalls: [], items: [{ id: "fc_9", type: "function_call", name: "memory_search", arguments: "{}" }] },
    { model: "m", decodeName: decode },
  );
  assert.equal(turn.toolCalls[0].id, "fc_9");
});

await test("finish reasons: completed, incomplete reasons, and unknown statuses", () => {
  assert.equal(mapResponseStatus("completed", undefined, false), "stop");
  assert.equal(mapResponseStatus("completed", undefined, true), "tool_use");
  assert.equal(mapResponseStatus("incomplete", "max_output_tokens", false), "max_tokens");
  assert.equal(mapResponseStatus("incomplete", "content_filter", false), "safety");
  assert.equal(mapResponseStatus("incomplete", "something_new", false), "other");
  assert.equal(mapResponseStatus("incomplete", undefined, true), "other");
  assert.equal(mapResponseStatus("weird", undefined, true), "tool_use");
  assert.equal(mapResponseStatus("weird", undefined, false), "other");
});

/* ─── The adapter over a fake network ──────────────────────── */

const publicHost = async () => ["203.0.113.10"];
// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const KEY = ["sk", "proj", "TESTKEY" + "z".repeat(16)].join("-");

function fakeNetwork(...files) {
  const seen = [];
  const fetch = async (url, init) => {
    seen.push({ url: String(url), init, body: JSON.parse(init.body) });
    const name = files[Math.min(seen.length - 1, files.length - 1)];
    return new Response(fixtureBytes(name), { status: 200, headers: { "content-type": "text/event-stream", "x-request-id": "req_net" } });
  };
  return { seen, fetch };
}

await test("call: POSTs {base}/responses with bearer auth and the optional org/project headers, and decodes the answer", async () => {
  const net = fakeNetwork("tool-call.sse");
  const adapter = createOpenAiAdapter({ fetch: net.fetch, resolveHost: publicHost });
  const turn = await adapter.call(request(), { creds: { apiKey: KEY, organization: "org-abc123", project: "proj_xyz789" } });
  assert.equal(net.seen.length, 1);
  assert.equal(net.seen[0].url, "https://api.openai.com/v1/responses");
  const h = net.seen[0].init.headers;
  assert.equal(h.Authorization, `Bearer ${KEY}`);
  assert.equal(h["OpenAI-Organization"], "org-abc123");
  assert.equal(h["OpenAI-Project"], "proj_xyz789");
  assert.equal(h.accept, "text/event-stream");
  assert.equal(net.seen[0].init.redirect, "manual");
  assert.equal(net.seen[0].body.store, false);
  assert.equal(turn.requestId, "req_net");
  assert.equal(turn.toolCalls[0].name, "xsiam.run_xql_query");
  assert.ok(!JSON.stringify(turn).includes(KEY));
});

await test("call: without org/project no such headers are sent; an invalid id is never put in a header; a custom base URL is used", async () => {
  const net = fakeNetwork("text-only.sse");
  const adapter = createOpenAiAdapter({ fetch: net.fetch, resolveHost: publicHost });
  await adapter.call(request(), { creds: { apiKey: KEY, baseUrl: "https://llm.gateway.example.com/openai/v1/", organization: "bad value\r\nX-Evil: 1", project: "" } });
  const h = net.seen[0].init.headers;
  assert.equal(net.seen[0].url, "https://llm.gateway.example.com/openai/v1/responses");
  assert.equal("OpenAI-Organization" in h, false);
  assert.equal("OpenAI-Project" in h, false);
  assert.equal("X-Evil" in h, false);
});

await test("call: no API key fails with PROVIDER_NOT_CONFIGURED before any network use", async () => {
  const net = fakeNetwork("text-only.sse");
  const adapter = createOpenAiAdapter({ fetch: net.fetch, resolveHost: publicHost });
  try { await adapter.call(request(), { creds: { apiKey: "  " } }); assert.fail("expected a rejection"); }
  catch (e) { assert.ok(e instanceof ProviderError); assert.equal(e.code, "PROVIDER_NOT_CONFIGURED"); assert.match(e.message, /OpenAI API key/); }
  assert.equal(net.seen.length, 0);
});

await test("call: adapter events (tool_choice_downgraded) reach onEvent before the request is sent", async () => {
  const net = fakeNetwork("text-only.sse");
  const adapter = createOpenAiAdapter({ fetch: net.fetch, resolveHost: publicHost, lookupRules: () => null });
  const events = [];
  await adapter.call(request({ toolChoice: "required" }), { creds: { apiKey: KEY }, onEvent: (e) => events.push(e.type) });
  assert.deepEqual(events, ["tool_choice_downgraded"]);
  assert.equal(net.seen[0].body.tool_choice, "auto");
});

await test("a tool loop round trip: the second request replays the first answer (reasoning with encrypted content, the call) and its output", async () => {
  const net = fakeNetwork("tool-call.sse", "text-only.sse");
  const adapter = createOpenAiAdapter({ fetch: net.fetch, resolveHost: publicHost });
  const messages = [{ role: "user", text: "scan the host" }];
  const first = await adapter.call(request({ messages }), { creds: { apiKey: KEY } });
  messages.push({ role: "assistant_turn", turn: first });
  messages.push({ role: "tool_results", items: [{ kind: "result", callId: first.toolCalls[0].id, name: first.toolCalls[0].name, payload: { result: "3 rows" } }] });
  await adapter.call(request({ messages }), { creds: { apiKey: KEY } });
  const input = net.seen[1].body.input;
  assert.deepEqual(input.map((i) => i.type), ["message", "reasoning", "function_call", "function_call_output"]);
  assert.equal(input[1].encrypted_content, "ENC_BLOB_1");
  assert.equal(input[2].call_id, "call_abc");
  assert.deepEqual(input[3], { type: "function_call_output", call_id: "call_abc", output: '{"result":"3 rows"}' });
  // Every function_call in the input has exactly one output.
  const calls = input.filter((i) => i.type === "function_call").map((i) => i.call_id);
  const outs = input.filter((i) => i.type === "function_call_output").map((i) => i.call_id);
  assert.deepEqual(calls.sort(), outs.sort());
});

await test("listModels and testConnection read GET {base}/models with the same headers", async () => {
  const seen = [];
  const fetch = async (url, init) => {
    seen.push({ url: String(url), init });
    return new Response(JSON.stringify({ object: "list", data: [{ id: "gpt-6-sol" }, { id: "text-embedding-3-large" }] }), { status: 200, headers: { "content-type": "application/json" } });
  };
  const adapter = createOpenAiAdapter({ fetch, resolveHost: publicHost });
  const live = await adapter.listModels({ apiKey: KEY, organization: "org-abc123" }, new AbortController().signal);
  assert.deepEqual(live.map((m) => m.id), ["gpt-6-sol", "text-embedding-3-large"]);
  assert.equal(seen[0].url, "https://api.openai.com/v1/models");
  assert.equal(seen[0].init.headers["OpenAI-Organization"], "org-abc123");
  const test = await adapter.testConnection({ apiKey: KEY });
  assert.equal(test.ok, true);
  assert.equal(test.modelCount, 2);
  assert.match(test.message, /2 models visible, including GPT-6 Sol/);
  assert.ok(!test.message.includes(KEY));
});

/* ─── Dispatch ─────────────────────────────────────────────── */

await test("dispatch resolves an OpenAI adapter with no leak or empty-turn retries", () => {
  const adapter = dispatch.resolveAdapter({ provider: "openai", model: "gpt-6-sol" });
  assert.equal(adapter.id, "openai");
  assert.deepEqual(adapter.capabilities, { leakRecovery: false, emptyTurnRetry: false });
  assert.deepEqual(dispatch.capabilitiesFor({ provider: "openai", model: "gpt-6-sol" }), { leakRecovery: false, emptyTurnRetry: false });
});

await test("dispatch ignores the caller's (Google) credentials and sends only the stored OpenAI ones", async () => {
  let received;
  const fake = { id: "openai", capabilities: { leakRecovery: false, emptyTurnRetry: false }, async call(_req, ctx) { received = ctx.creds; return { provider: "openai", model: "m", text: [], thinking: [], toolCalls: [], finish: "stop", usage: null, leakedToolCallSuspected: false, raw: [] }; } };
  const stored = { apiKey: KEY, organization: "org-abc123" };
  await dispatch.callModel(request(), { creds: { apiKey: "AIza-caller-google-key", serviceAccountJson: "{}" } }, { adapters: { openai: fake }, resolveCreds: async (p) => (p === "openai" ? stored : null) });
  assert.deepEqual(received, stored);
});

await test("dispatch with no stored OpenAI instance fails with PROVIDER_NOT_CONFIGURED naming OpenAI, and never calls the adapter", async () => {
  let called = false;
  const fake = { id: "openai", capabilities: {}, async call() { called = true; } };
  try {
    await dispatch.callModel(request(), { creds: { apiKey: "AIza-caller-google-key" } }, { adapters: { openai: fake }, resolveCreds: async () => null });
    assert.fail("expected a rejection");
  } catch (e) {
    assert.ok(e instanceof ProviderError);
    assert.equal(e.code, "PROVIDER_NOT_CONFIGURED");
    assert.match(e.message, /OpenAI/);
  }
  assert.equal(called, false);
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall OpenAI mapping tests passed");
