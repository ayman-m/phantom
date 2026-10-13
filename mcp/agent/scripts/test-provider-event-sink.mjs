#!/usr/bin/env node
/**
 * Adapter observations (lib/providers/event-sink.ts): the sink the chat route
 * hands to every model call as `onEvent`. An observation such as
 * tool_choice_downgraded, tool_call_truncated, unknown_tool_name or refusal is
 * written once per sink to the SSE `debug` stream (stage/detail plus the
 * structured fields, a Wire-events line and no thread text) and to the
 * `provider_event` audit log; a failing output never reaches the model call;
 * oversize data is capped. A source check pins that the route passes a sink at
 * every model-call site, and an end-to-end case drives a real adapter.
 *
 *   node scripts/test-provider-event-sink.mjs   (npm run test:provider-event-sink)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node
 * without it the test skips (the build type-checks the modules).
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

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const sink = await import("../lib/providers/event-sink.ts");
const { createOpenAiAdapter } = await import("../lib/providers/openai/adapter.ts");
const { createAnthropicAdapter } = await import("../lib/providers/anthropic/adapter.ts");

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

const REF = { provider: "openai", model: "gpt-6-sol" };
function harness(over = {}) {
  const sent = [];
  const audits = [];
  const onEvent = sink.createProviderEventSink({
    ref: REF,
    purpose: "chat",
    sessionId: "sess-1",
    sendEvent: (kind, data) => sent.push({ kind, data }),
    audit: (action, row) => { audits.push({ action, row }); },
    ...over,
  });
  return { sent, audits, onEvent };
}
const downgrade = { type: "tool_choice_downgraded", message: "Forced tool use was changed to auto.", data: { model: "gpt-6-sol", requested: "required", sent: "auto" } };

await test("an observation goes to the SSE debug stream in the route's debug shape and to the audit log", () => {
  const h = harness();
  h.onEvent(downgrade);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].kind, "debug");
  assert.deepEqual(h.sent[0].data, {
    stage: "provider",
    detail: "tool_choice_downgraded: Forced tool use was changed to auto.",
    provider: "openai",
    model: "gpt-6-sol",
    purpose: "chat",
    type: "tool_choice_downgraded",
    data: { model: "gpt-6-sol", requested: "required", sent: "auto" },
  });
  assert.equal(h.audits.length, 1);
  assert.equal(h.audits[0].action, "provider_event");
  assert.deepEqual(h.audits[0].row, {
    target: "session:sess-1",
    status: "success",
    metadata: { provider: "openai", model: "gpt-6-sol", purpose: "chat", type: "tool_choice_downgraded", message: "Forced tool use was changed to auto.", data: { model: "gpt-6-sol", requested: "required", sent: "auto" } },
  });
});

await test("the same observation is written once per sink; a different one, or different data, is written", () => {
  const h = harness();
  h.onEvent(downgrade);
  h.onEvent({ ...downgrade });
  h.onEvent({ type: "unknown_tool_name", message: "x", data: { name: "a" } });
  h.onEvent({ type: "unknown_tool_name", message: "x", data: { name: "b" } });
  h.onEvent({ type: "unknown_tool_name", message: "x", data: { name: "a" } });
  assert.equal(h.sent.length, 3);
  assert.equal(h.audits.length, 3);
  // A new sink (the next turn) starts clean.
  const next = harness();
  next.onEvent(downgrade);
  assert.equal(next.sent.length, 1);
});

await test("an observation without data has no data field; oversize data is replaced by a marker", () => {
  const h = harness();
  h.onEvent({ type: "refusal", message: "The model declined to answer." });
  assert.equal("data" in h.sent[0].data, false);
  assert.equal("data" in h.audits[0].row.metadata, false);
  h.onEvent({ type: "refusal", message: "again", data: { stop_details: "x".repeat(sink.MAX_EVENT_DATA_CHARS + 1) } });
  assert.deepEqual(h.sent[1].data.data, { truncated: true });
  const circular = {};
  circular.self = circular;
  h.onEvent({ type: "weird", message: "m", data: circular });
  assert.deepEqual(h.sent[2].data.data, { truncated: true });
});

await test("a sink with no outputs, a throwing stream and a throwing or rejecting audit never throw", async () => {
  sink.createProviderEventSink({ ref: REF, purpose: "chat", sessionId: "s" })(downgrade);
  const h1 = harness({ sendEvent: () => { throw new Error("stream closed"); } });
  h1.onEvent(downgrade);
  assert.equal(h1.audits.length, 1, "the audit still happens when the stream is closed");
  const h2 = harness({ audit: () => { throw new Error("audit down"); } });
  h2.onEvent(downgrade);
  assert.equal(h2.sent.length, 1);
  const h3 = harness({ audit: async () => { throw new Error("audit rejected"); } });
  h3.onEvent(downgrade);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h3.sent.length, 1);
});

await test("the thread is untouched: the only SSE event a sink sends is `debug`", () => {
  const h = harness();
  for (const type of ["tool_choice_downgraded", "tool_call_truncated", "unknown_tool_name", "refusal"]) h.onEvent({ type, message: type, data: { n: type } });
  assert.ok(h.sent.every((s) => s.kind === "debug"));
  assert.ok(h.sent.every((s) => !("text" in s.data)), "no text_delta payload");
});

/* ─── End to end with real adapters ────────────────────────── */

const publicHost = async () => ["203.0.113.10"];
const sse = (events) => events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
const KEY = ["sk", "proj", "TESTKEY" + "w".repeat(16)].join("-");
const request = (over = {}) => ({
  ref: REF, system: "s", messages: [{ role: "user", text: "hi" }],
  tools: [{ name: "memory_search", description: "d", inputSchema: { type: "object", properties: {} } }],
  toolChoice: "auto", thinking: true, purpose: "chat", ...over,
});

await test("an OpenAI call that refuses reaches the sink as a refusal observation", async () => {
  const body = sse([
    { type: "response.created", response: { status: "in_progress" } },
    { type: "response.completed", response: { status: "completed", output: [{ id: "m", type: "message", role: "assistant", content: [{ type: "refusal", refusal: "No." }] }], usage: { input_tokens: 5, output_tokens: 2 } } },
  ]);
  const fetch = async () => new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  const h = harness();
  const turn = await createOpenAiAdapter({ fetch, resolveHost: publicHost }).call(request(), { creds: { apiKey: KEY }, onEvent: h.onEvent });
  assert.equal(turn.finish, "refusal");
  assert.deepEqual(h.sent.map((s) => s.data.type), ["refusal"]);
  assert.equal(h.audits[0].row.metadata.type, "refusal");
  assert.ok(!JSON.stringify([h.sent, h.audits]).includes(KEY));
});

await test("a forced tool choice the model rejects, and an unknown tool name, both reach the sink (OpenAI and Claude)", async () => {
  const openai = sse([
    { type: "response.completed", response: { status: "completed", output: [{ id: "f", type: "function_call", call_id: "c1", name: "not_advertised", arguments: "{}" }], usage: {} } },
  ]);
  const h = harness();
  await createOpenAiAdapter({ fetch: async () => new Response(openai, { status: 200, headers: { "content-type": "text/event-stream" } }), resolveHost: publicHost, lookupRules: () => null })
    .call(request({ toolChoice: "required" }), { creds: { apiKey: KEY }, onEvent: h.onEvent });
  assert.deepEqual(h.sent.map((s) => s.data.type), ["tool_choice_downgraded", "unknown_tool_name"]);

  const anthropic = sse([
    { type: "message_start", message: { id: "m", model: "x", usage: {} } },
    { type: "content_block_start", index: 0, content_block: { type: "tool_use", id: "t1", name: "ghost", input: {} } },
    { type: "content_block_stop", index: 0 },
    { type: "message_delta", delta: { stop_reason: "tool_use" }, usage: {} },
    { type: "message_stop" },
  ]);
  const h2 = harness({ ref: { provider: "anthropic", model: "claude-opus-5-5" } });
  await createAnthropicAdapter({ fetch: async () => new Response(anthropic, { status: 200, headers: { "content-type": "text/event-stream" } }), resolveHost: publicHost })
    .call(request({ ref: { provider: "anthropic", model: "claude-opus-5-5" } }), { creds: { apiKey: ["sk", "ant", "TESTKEY" + "w".repeat(16)].join("-") }, onEvent: h2.onEvent });
  assert.deepEqual(h2.sent.map((s) => s.data.type), ["unknown_tool_name"]);
  assert.equal(h2.sent[0].data.provider, "anthropic");
});

/* ─── The route passes a sink at every model-call site ─────── */

const routeSource = readFileSync(join(root, "app", "api", "chat", "route.ts"), "utf8");

await test("route glue: every callModel call passes onEvent", () => {
  const calls = [...routeSource.matchAll(/\bcallModel\(/g)].map((m) => m.index);
  assert.ok(calls.length >= 2, "the main loop and the subagent");
  for (const at of calls) {
    const window = routeSource.slice(at, at + 1400);
    assert.ok(/onEvent:/.test(window), `callModel at offset ${at} has no onEvent: ${window.slice(0, 80)}`);
  }
});

await test("route glue: every summarizeViaModel call passes a sink, and the helper forwards it to summarizeText", () => {
  const helper = routeSource.indexOf("function summarizeViaModel(");
  assert.ok(helper > 0);
  const helperBody = routeSource.slice(helper, helper + 700);
  assert.ok(/onEvent\?: \(event: ProviderEvent\) => void/.test(helperBody));
  assert.ok(/\{ creds: credsFromRuntimeConfig\(runtimeConfig\), onEvent, signal \}/.test(helperBody), "sink and signal forwarded to summarizeText");
  const sites = [...routeSource.matchAll(/summarizeViaModel\(/g)].map((m) => m.index).filter((i) => i !== helper + "function ".length);
  assert.equal(sites.length, 3, "/compress, /plan and auto-compaction");
  for (const at of sites) {
    const window = routeSource.slice(at, at + 420);
    assert.ok(/ProviderEvents|providerEventSink\(/.test(window), `summarizeViaModel at offset ${at} passes no sink: ${window.slice(0, 120)}`);
  }
});

await test("route glue: the sinks name the call's purpose and ride the stream's own sendEvent", () => {
  assert.ok(/purpose: 'chat', sessionId, trigger, sendEvent/.test(routeSource));
  assert.ok(/purpose: 'subagent',/.test(routeSource));
  assert.ok(/purpose: 'plan', sessionId, trigger, sendEvent/.test(routeSource));
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall provider event sink tests passed");
