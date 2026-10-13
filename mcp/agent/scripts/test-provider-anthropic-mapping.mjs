#!/usr/bin/env node
/**
 * Anthropic Messages mapping (lib/providers/anthropic/{payload,adapter}.ts,
 * lib/providers/schema.ts toPortableSchema, lib/providers/dispatch.ts):
 * message merging and ordering, tool_result and directive blocks, replay of
 * native content, thinking modes per model, tool_choice rules, max_tokens,
 * cache_control, the absence of sampling parameters, tool-name encoding, and
 * the credential rule at dispatch.
 *
 *   node scripts/test-provider-anthropic-mapping.mjs   (npm run test:provider-anthropic-mapping)
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

const payload = await import("../lib/providers/anthropic/payload.ts");
const { createAnthropicAdapter, toAssistantTurn, mapStopReason } = await import("../lib/providers/anthropic/adapter.ts");
const { readAnthropicStream } = await import("../lib/providers/anthropic/stream.ts");
const { toPortableSchema } = await import("../lib/providers/schema.ts");
const { lookupModelFacts } = await import("../lib/providers/registry/lookup.ts");
const dispatch = await import("../lib/providers/dispatch.ts");
const { ProviderError } = await import("../lib/providers/errors.ts");
const { buildToolNameCodec } = await import("../lib/providers/tool-names.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "anthropic-sse");

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
    ref: { provider: "anthropic", model: "claude-opus-5-5" },
    system: "You are Phantom.",
    messages: [{ role: "user", text: "hello" }],
    tools: TOOLS,
    toolChoice: "auto",
    thinking: true,
    purpose: "chat",
    ...over,
  };
}
const build = (over, model = "claude-opus-5-5", rulesOverride) =>
  payload.buildAnthropicRequest(request({ ...over, ref: { provider: "anthropic", model } }), {
    rules: rulesOverride === undefined ? lookupModelFacts(`anthropic/${model}`) : rulesOverride,
    maxTokensCap: CAP,
  });

const texts = (msg) => msg.content.map((b) => b.text ?? b.type);

/* ─── System, caching, sampling, limits ─────────────────────── */

await test("system is a block list with cache_control; automatic caching is on; the body streams", () => {
  const { body } = build();
  assert.deepEqual(body.system, [{ type: "text", text: "You are Phantom.", cache_control: { type: "ephemeral" } }]);
  assert.deepEqual(body.cache_control, { type: "ephemeral" });
  assert.equal(body.stream, true);
  assert.equal(body.model, "claude-opus-5-5");
});

await test("an empty system prompt is omitted, not sent as an empty block", () => {
  assert.equal("system" in build({ system: "   " }).body, false);
});

await test("one-shot summarize and plan calls are not cached; subagent and budget summary are", () => {
  for (const purpose of ["summarize", "plan"]) {
    const { body } = build({ purpose });
    assert.equal("cache_control" in body, false, purpose);
    assert.equal("cache_control" in body.system[0], false, purpose);
  }
  for (const purpose of ["chat", "subagent", "budget_summary"]) {
    assert.deepEqual(build({ purpose }).body.cache_control, { type: "ephemeral" }, purpose);
  }
});

await test("temperature, top_p and top_k are never sent, for any model, thinking state or tool choice", () => {
  for (const model of ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5", "claude-sonnet-5"]) {
    for (const thinking of [true, false]) {
      for (const toolChoice of ["auto", "required", "none"]) {
        const { body } = build({ thinking, toolChoice }, model);
        for (const key of ["temperature", "top_p", "top_k"]) assert.equal(key in body, false, `${model} ${key}`);
      }
    }
  }
});

await test("max_tokens is min(model maximum, 65536); an unknown model gets the conservative 32000", () => {
  assert.equal(build().body.max_tokens, 65_536, "128K model is capped");
  assert.equal(build({}, "claude-opus-5").body.max_tokens, payload.UNKNOWN_MODEL_MAX_TOKENS, "maxOutput not stated");
  assert.equal(build({}, "claude-not-in-registry", null).body.max_tokens, 32_000);
  const small = { maxOutput: 4096, forcedToolChoice: false, thinking: { on: "none", offMode: "omit" } };
  assert.equal(build({}, "x", small).body.max_tokens, 4096);
});

/* ─── Messages ─────────────────────────────────────────────── */

await test("adjacent same-role messages merge; roles alternate", () => {
  const { body } = build({
    messages: [
      { role: "user", text: "one" },
      { role: "user", text: "two" },
      { role: "assistant", text: "a1" },
      { role: "assistant", text: "a2" },
      { role: "user", text: "three" },
    ],
  });
  assert.deepEqual(body.messages.map((m) => m.role), ["user", "assistant", "user"]);
  assert.deepEqual(texts(body.messages[0]), ["one", "two"]);
  assert.deepEqual(texts(body.messages[1]), ["a1", "a2"]);
});

await test("blank text is dropped and a message left empty disappears; an all-empty request gets a placeholder", () => {
  const { body } = build({
    messages: [{ role: "user", text: "  " }, { role: "assistant", text: "" }, { role: "user", text: "real" }],
  });
  assert.equal(body.messages.length, 1);
  assert.deepEqual(texts(body.messages[0]), ["real"]);
  const empty = build({ messages: [{ role: "user", text: "" }] }).body;
  assert.deepEqual(empty.messages, [{ role: "user", content: [{ type: "text", text: payload.PLACEHOLDER_EMPTY_USER }] }]);
});

await test("a first assistant message gets a user placeholder; a last assistant message gets a user nudge", () => {
  const { body } = build({ messages: [{ role: "assistant", text: "earlier" }, { role: "user", text: "q" }, { role: "assistant", text: "half" }] });
  assert.deepEqual(body.messages.map((m) => m.role), ["user", "assistant", "user", "assistant", "user"]);
  assert.equal(body.messages[0].content[0].text, payload.PLACEHOLDER_FIRST_USER);
  assert.equal(body.messages.at(-1).content[0].text, payload.PLACEHOLDER_LAST_USER);
});

const TOOL_TURN = {
  provider: "anthropic", model: "claude-opus-5-5", text: [], thinking: [], finish: "tool_use", usage: null, leakedToolCallSuspected: false,
  toolCalls: [{ id: "toolu_A", name: "xsiam.run_xql_query", args: {} }, { id: "toolu_B", name: "memory_search", args: {} }],
  raw: [
    { type: "thinking", thinking: "", signature: "sig-1" },
    { type: "redacted_thinking", data: "opaque" },
    { type: "text", text: "  " },
    { type: "text", text: "checking" },
    { type: "tool_use", id: "toolu_A", name: "xsiam__run_xql_query", input: { query: "q" } },
    { type: "tool_use", id: "toolu_B", name: "memory_search", input: {} },
  ],
};

await test("tool results: every tool_result block first, in call order, then each directive as a text block", () => {
  const { body } = build({
    messages: [
      { role: "user", text: "go" },
      { role: "assistant_turn", turn: TOOL_TURN },
      {
        role: "tool_results",
        items: [
          { kind: "result", callId: "toolu_A", name: "xsiam.run_xql_query", payload: { result: { rows: 2 } } },
          { kind: "directive", text: "Stop calling tools." },
          { kind: "result", callId: "toolu_B", name: "memory_search", payload: { error: "boom" } },
        ],
      },
    ],
  });
  assert.deepEqual(body.messages.map((m) => m.role), ["user", "assistant", "user"]);
  assert.deepEqual(body.messages[2].content, [
    { type: "tool_result", tool_use_id: "toolu_A", content: JSON.stringify({ result: { rows: 2 } }) },
    { type: "tool_result", tool_use_id: "toolu_B", content: JSON.stringify({ error: "boom" }), is_error: true },
    { type: "text", text: "Stop calling tools." },
  ]);
});

await test("a user message that follows tool results merges into the same message, tool_results still first", () => {
  const { body } = build({
    messages: [
      { role: "user", text: "go" },
      { role: "assistant_turn", turn: TOOL_TURN },
      { role: "tool_results", items: [{ kind: "result", callId: "toolu_A", name: "x", payload: { result: 1 } }, { kind: "result", callId: "toolu_B", name: "y", payload: { result: 2 } }] },
      { role: "user", text: "Tool budget reached." },
    ],
  });
  assert.equal(body.messages.length, 3);
  assert.deepEqual(body.messages[2].content.map((b) => b.type), ["tool_result", "tool_result", "text"]);
  assert.equal(body.messages[2].content[2].text, "Tool budget reached.");
});

await test("an in-loop assistant turn replays its native blocks verbatim: thinking, signatures and tool_use names untouched", () => {
  const { body } = build({
    messages: [{ role: "user", text: "go" }, { role: "assistant_turn", turn: TOOL_TURN }, { role: "tool_results", items: [{ kind: "result", callId: "toolu_A", name: "x", payload: { result: 1 } }, { kind: "result", callId: "toolu_B", name: "y", payload: { result: 1 } }] }],
  });
  assert.deepEqual(body.messages[1].content, [
    { type: "thinking", thinking: "", signature: "sig-1" },
    { type: "redacted_thinking", data: "opaque" },
    { type: "text", text: "checking" },
    { type: "tool_use", id: "toolu_A", name: "xsiam__run_xql_query", input: { query: "q" } },
    { type: "tool_use", id: "toolu_B", name: "memory_search", input: {} },
  ], "only the blank text block is gone");
});

const TOOL_LOOP = [
  { role: "user", text: "go" },
  { role: "assistant_turn", turn: TOOL_TURN },
  { role: "tool_results", items: [{ kind: "result", callId: "toolu_A", name: "x", payload: { result: 1 } }, { kind: "result", callId: "toolu_B", name: "y", payload: { result: 1 } }] },
];
const BLOCK_TYPES_WITH_THINKING = ["thinking", "redacted_thinking", "text", "tool_use", "tool_use"];

await test("thinking truly off (Haiku 5.5 disabled) strips replayed thinking blocks; thinking on keeps them", () => {
  const off = build({ messages: TOOL_LOOP, thinking: false, toolChoice: "none" }, "claude-haiku-5-5").body;
  assert.deepEqual(off.messages[1].content.map((b) => b.type), ["text", "tool_use", "tool_use"]);
  const on = build({ messages: TOOL_LOOP, thinking: true }, "claude-haiku-5-5").body;
  assert.deepEqual(on.messages[1].content.map((b) => b.type), BLOCK_TYPES_WITH_THINKING);
  assert.deepEqual(payload.stripThinkingBlocks(TOOL_TURN.raw).map((b) => b.type), ["text", "text", "tool_use", "tool_use"]);
});

await test("thinking off where the model still thinks (Sonnet 5.5 between_tools, Opus 5.5 and Fable 5.1 low effort) keeps replayed thinking blocks", () => {
  for (const model of ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]) {
    for (const toolChoice of ["auto", "none"]) {
      const { body } = build({ messages: TOOL_LOOP, thinking: false, toolChoice }, model);
      assert.deepEqual(body.messages[1].content.map((b) => b.type), BLOCK_TYPES_WITH_THINKING, `${model} ${toolChoice}`);
      assert.deepEqual(body.messages[1].content[0], { type: "thinking", thinking: "", signature: "sig-1" }, "signature untouched");
    }
  }
});

/* ─── Thinking per model ───────────────────────────────────── */

const THINKING_CASES = [
  // [model, thinking on -> thinking/output_config, off -> thinking/output_config]
  ["claude-fable-5-1", { thinking: { type: "adaptive", display: "summarized" } }, { output_config: { effort: "low" } }],
  ["claude-opus-5-5", { thinking: { type: "adaptive", display: "summarized" } }, { output_config: { effort: "low" } }],
  ["claude-sonnet-5-5", { thinking: { type: "adaptive", display: "summarized" } }, { thinking: { type: "between_tools" } }],
  ["claude-haiku-5-5", { thinking: { type: "adaptive", display: "summarized" } }, { thinking: { type: "disabled" } }],
  ["claude-opus-5", { thinking: { type: "adaptive", display: "summarized" } }, { thinking: { type: "disabled" } }],
];

for (const [model, on, off] of THINKING_CASES) {
  await test(`thinking modes: ${model}`, () => {
    for (const [state, expected] of [[true, on], [false, off]]) {
      const { body } = build({ thinking: state }, model);
      assert.deepEqual(body.thinking, expected.thinking, `${model} thinking=${state} thinking`);
      assert.deepEqual(body.output_config, expected.output_config, `${model} thinking=${state} output_config`);
    }
    // Neither display nor effort ever rides along with a disable or between_tools.
    const offBody = build({ thinking: false }, model).body;
    if (offBody.thinking && offBody.thinking.type !== "adaptive") assert.equal("display" in offBody.thinking, false);
  });
}

await test("thinking modes: the budgeted mode sends enabled + budget_tokens below max_tokens, no display", () => {
  const rules = { maxOutput: 64_000, forcedToolChoice: false, thinking: { on: "enabled_budget", offMode: "disabled" } };
  const on = build({ thinking: true }, "legacy", rules).body;
  assert.deepEqual(on.thinking, { type: "enabled", budget_tokens: 16_000 });
  assert.ok(on.thinking.budget_tokens < on.max_tokens);
  assert.deepEqual(build({ thinking: false }, "legacy", rules).body.thinking, { type: "disabled" });
  const tiny = { ...rules, maxOutput: 1000 };
  assert.equal("thinking" in build({ thinking: true }, "legacy", tiny).body, false, "no room for the 1024 minimum budget");
});

await test("thinking modes: an unknown model and a model with no thinking get no thinking fields", () => {
  const none = { maxOutput: 8192, forcedToolChoice: false, thinking: { on: "none", offMode: "omit" } };
  for (const rules of [null, none]) {
    for (const thinking of [true, false]) {
      const { body } = build({ thinking }, "m", rules);
      assert.equal("thinking" in body, false);
      assert.equal("output_config" in body, false);
    }
  }
});

await test("effort is sent only for the low-effort case, using the lowest level the model lists", () => {
  const rules = { maxOutput: 8192, forcedToolChoice: false, thinking: { on: "adaptive", offMode: "low_effort", efforts: ["max", "high", "medium"] } };
  assert.deepEqual(build({ thinking: false }, "m", rules).body.output_config, { effort: "medium" });
  assert.equal("output_config" in build({ thinking: true }, "m", rules).body, false);
});

/* ─── tool_choice ──────────────────────────────────────────── */

await test("tool_choice required: forced only when the registry allows it AND thinking is off", () => {
  const forced = build({ toolChoice: "required", thinking: false }, "claude-haiku-5-5");
  assert.deepEqual(forced.body.tool_choice, { type: "any" });
  assert.deepEqual(forced.events, []);
});

await test("tool_choice required with thinking on is downgraded to auto, with a tool_choice_downgraded event", () => {
  const r = build({ toolChoice: "required", thinking: true }, "claude-haiku-5-5");
  assert.equal("tool_choice" in r.body, false);
  assert.equal(r.events.length, 1);
  assert.equal(r.events[0].type, "tool_choice_downgraded");
  assert.equal(r.events[0].data.thinkingActive, true);
});

await test("tool_choice required on models that reject forcing is downgraded even with thinking off", () => {
  for (const model of ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]) {
    const r = build({ toolChoice: "required", thinking: false }, model);
    assert.equal("tool_choice" in r.body, false, model);
    assert.equal(r.events[0].type, "tool_choice_downgraded", model);
  }
});

await test("tool_choice none keeps the tools and sends {type:none}; auto sends nothing", () => {
  const none = build({ toolChoice: "none" }).body;
  assert.equal(none.tools.length, 2, "both tools stay in the request");
  assert.deepEqual(none.tool_choice, { type: "none" });
  assert.equal("tool_choice" in build({ toolChoice: "auto" }).body, false);
});

await test("with no tools, neither tools nor tool_choice is sent", () => {
  for (const toolChoice of ["auto", "required", "none"]) {
    const { body, events } = build({ tools: [], toolChoice });
    assert.equal("tools" in body, false);
    assert.equal("tool_choice" in body, false);
    assert.deepEqual(events, [], "nothing to downgrade");
  }
});

/* ─── Tools ────────────────────────────────────────────────── */

await test("tools use wire names (dots -> __), portable schemas, and the alias pair collapses", () => {
  const dotted = tool("xsiam.run_xql_query", "Run XQL", { $schema: "https://json-schema.org/draft/2020-12/schema", type: "object", properties: { q: { $ref: "#/$defs/Q" } }, $defs: { Q: { type: "string", description: "the query" } } });
  const flat = { ...dotted, name: "xsiam_run_xql_query" };
  const { body, codec } = build({ tools: [dotted, flat, tool("cortex-xdr.get_cases", "Cases")] });
  assert.deepEqual(body.tools.map((t) => t.name), ["xsiam_run_xql_query", "cortex-xdr__get_cases"]);
  assert.deepEqual(body.tools[0].input_schema, { type: "object", properties: { q: { type: "string", description: "the query" } } });
  assert.equal(body.tools[0].description, "Run XQL");
  assert.equal(codec.decode("cortex-xdr__get_cases"), "cortex-xdr.get_cases");
  assert.equal(codec.decode("never_advertised"), undefined);
});

await test("a tool with no description is sent without one", () => {
  const { body } = build({ tools: [tool("t", "")] });
  assert.equal("description" in body.tools[0], false);
});

await test("toPortableSchema: refs inlined, $schema/$id dropped, top level forced to an object, top-level combinators removed", () => {
  const input = {
    $schema: "x", $id: "y", type: "string",
    anyOf: [{ type: "object" }],
    properties: { a: { $ref: "#/definitions/A", description: "own" }, $id: { type: "string" } },
    definitions: { A: { type: "integer", description: "theirs" } },
  };
  const before = JSON.stringify(input);
  const out = toPortableSchema(input);
  assert.equal(JSON.stringify(input), before, "input untouched");
  assert.deepEqual(out, { type: "object", properties: { a: { type: "integer", description: "own" }, $id: { type: "string" } } });
});

await test("toPortableSchema: recursion and unresolvable refs do not loop; non-objects become an empty object schema", () => {
  const rec = toPortableSchema({ type: "object", properties: { n: { $ref: "#/$defs/Node" } }, $defs: { Node: { type: "object", properties: { next: { $ref: "#/$defs/Node" } } } } });
  assert.equal(rec.properties.n.properties.next.description, "Recursive reference to Node");
  assert.deepEqual(toPortableSchema({ properties: { z: { $ref: "https://example.com/s.json" } } }), { type: "object", properties: { z: {} } });
  assert.deepEqual(toPortableSchema(undefined), { type: "object", properties: {} });
  assert.deepEqual(toPortableSchema({ properties: { e: { enum: [{ $ref: "kept" }] } } }).properties.e, { enum: [{ $ref: "kept" }] });
});

await test("a tool-name collision is a hard error", () => {
  assert.throws(() => build({ tools: [tool("a.b", "x"), tool("a__b", "y")] }), (e) => e instanceof ProviderError && e.code === "TOOL_NAME_COLLISION");
});

/* ─── Response mapping ─────────────────────────────────────── */

function streamOf(bytes) {
  return new ReadableStream({ start(c) { c.enqueue(new Uint8Array(bytes)); c.close(); } });
}
async function assembled(name) {
  return await readAnthropicStream(streamOf(readFileSync(join(fixtureDir, name))));
}

await test("a streamed turn maps to a neutral turn: tool names decoded, args parsed, usage normalized, raw replayable", async () => {
  const codec = buildToolNameCodec([tool("xsiam.run_xql_query", "x"), tool("memory_search", "y")], "claude");
  const events = [];
  const turn = toAssistantTurn(await assembled("tool-use-crlf.sse"), { model: "claude-opus-5-5", decodeName: codec.decode, requestId: "req_9", onEvent: (e) => events.push(e) });
  assert.equal(turn.provider, "anthropic");
  assert.equal(turn.finish, "tool_use");
  assert.equal(turn.finishDetail, "tool_use");
  assert.deepEqual(turn.text, ["Let me check."]);
  assert.deepEqual(turn.thinking, ["Need the events table."]);
  assert.deepEqual(turn.toolCalls, [
    { id: "toolu_01SyntheticA", name: "xsiam.run_xql_query", args: { query: "dataset = x | limit 5", limit: 5 } },
    { id: "toolu_01SyntheticB", name: "memory_search", args: {} },
  ]);
  assert.equal(turn.requestId, "req_9");
  assert.equal(turn.usage.inputTotal, 2030);
  assert.equal(turn.leakedToolCallSuspected, false);
  assert.equal(turn.raw.length, 5);
  assert.equal(events.length, 0);
  // Replaying the turn produces the same blocks the API sent.
  const { body } = build({ messages: [{ role: "user", text: "q" }, { role: "assistant_turn", turn }, { role: "tool_results", items: turn.toolCalls.map((c) => ({ kind: "result", callId: c.id, name: c.name, payload: { result: 1 } })) }] });
  assert.deepEqual(body.messages[1].content, turn.raw);
});

await test("an unadvertised tool name is passed through as written and reported", async () => {
  const events = [];
  const turn = toAssistantTurn(await assembled("tool-use-crlf.sse"), { model: "m", decodeName: () => undefined, onEvent: (e) => events.push(e) });
  assert.deepEqual(turn.toolCalls.map((c) => c.name), ["xsiam__run_xql_query", "memory_search"]);
  assert.deepEqual(events.map((e) => e.type), ["unknown_tool_name", "unknown_tool_name"]);
});

await test("finish reasons: end_turn, tool_use, max_tokens (tool dropped), refusal, context exceeded, pause_turn", async () => {
  assert.equal(mapStopReason("end_turn", false), "stop");
  assert.equal(mapStopReason("stop_sequence", false), "stop");
  assert.equal(mapStopReason("tool_use", true), "tool_use");
  assert.equal(mapStopReason("tool_use", false), "other", "no call survived");
  assert.equal(mapStopReason("pause_turn", false), "other");
  assert.equal(mapStopReason(null, false), "other");

  const ev = [];
  const cut = toAssistantTurn(await assembled("truncated-tool.sse"), { model: "m", decodeName: (w) => w, onEvent: (e) => ev.push(e) });
  assert.equal(cut.finish, "max_tokens");
  assert.deepEqual(cut.toolCalls, []);
  assert.deepEqual(ev.map((e) => e.type), ["tool_call_truncated"]);

  const refEv = [];
  const ref = toAssistantTurn(await assembled("refusal.sse"), { model: "m", decodeName: (w) => w, onEvent: (e) => refEv.push(e) });
  assert.equal(ref.finish, "refusal");
  assert.equal(refEv[0].type, "refusal");
  assert.deepEqual(refEv[0].data.stop_details, { category: "example-category", explanation: "synthetic refusal" });

  const ctx = toAssistantTurn(await assembled("context-exceeded.sse"), { model: "m", decodeName: (w) => w });
  assert.equal(ctx.finish, "context_exceeded");
  assert.deepEqual(ctx.text, ["Cut short"]);
});

/* ─── Adapter over a fake network ──────────────────────────── */

function fakeFetch(handler) {
  const seen = [];
  const impl = async (url, init) => {
    seen.push({ url, init, body: init.body ? JSON.parse(init.body) : null });
    return handler(url, init, seen.length);
  };
  impl.seen = seen;
  return impl;
}
function sseResponse(name, headers = {}) {
  return new Response(readFileSync(join(fixtureDir, name)), {
    status: 200,
    headers: { "content-type": "text/event-stream", "request-id": "req_synthetic01", ...headers },
  });
}
const publicHost = async () => ["203.0.113.10"];
const CREDS = { apiKey: "sk-ant-test12345678" };

await test("adapter.call: POST {base}/v1/messages with Bearer auth, the version header, no beta header, and a neutral turn back", async () => {
  const f = fakeFetch(() => sseResponse("tool-use-crlf.sse"));
  const adapter = createAnthropicAdapter({ fetch: f, resolveHost: publicHost });
  const events = [];
  const turn = await adapter.call(request({ toolChoice: "required" }), { creds: { ...CREDS, baseUrl: "https://gateway.example.com/" }, onEvent: (e) => events.push(e) });
  const call = f.seen[0];
  assert.equal(call.url, "https://gateway.example.com/v1/messages");
  assert.equal(call.init.method, "POST");
  assert.equal(call.init.redirect, "manual");
  assert.equal(call.init.headers.Authorization, "Bearer sk-ant-test12345678");
  assert.equal(call.init.headers["anthropic-version"], "2023-06-01");
  assert.equal("anthropic-beta" in call.init.headers, false);
  assert.equal(call.init.headers.accept, "text/event-stream");
  assert.equal(call.body.model, "claude-opus-5-5");
  assert.equal(call.body.stream, true);
  assert.equal(turn.requestId, "req_synthetic01");
  assert.equal(turn.toolCalls.length, 2);
  assert.deepEqual(events.map((e) => e.type), ["tool_choice_downgraded"], "Opus 5.5 rejects forced tool use");
  assert.equal(adapter.id, "anthropic");
  assert.deepEqual(adapter.capabilities, { leakRecovery: false, emptyTurnRetry: false });
});

await test("adapter: betas, when a request asks for them, travel in one comma-joined header", async () => {
  const { requestHeaders } = await import("../lib/providers/anthropic/transport.ts");
  assert.equal(requestHeaders("k", ["a-beta", "b-beta"])["anthropic-beta"], "a-beta,b-beta");
  assert.equal("anthropic-beta" in requestHeaders("k", []), false);
});

await test("adapter.estimateToolsPayload renders the wire catalog; a collision falls back to the specs", () => {
  const adapter = createAnthropicAdapter();
  assert.deepEqual(adapter.estimateToolsPayload(TOOLS).map((t) => t.name), ["xsiam__run_xql_query", "memory_search"]);
  const colliding = [tool("a.b", "x"), tool("a__b", "y")];
  assert.equal(adapter.estimateToolsPayload(colliding), colliding);
});

await test("adapter.testConnection and listModels reuse GET /v1/models and report the count and recommended models", async () => {
  const f = fakeFetch(() => new Response(JSON.stringify({ data: [{ id: "claude-opus-5-5", display_name: "Opus" }, { id: "claude-sonnet-5-5" }, { id: "other" }], has_more: false }), { status: 200, headers: { "content-type": "application/json" } }));
  const adapter = createAnthropicAdapter({ fetch: f, resolveHost: publicHost });
  const r = await adapter.testConnection(CREDS);
  assert.equal(r.ok, true);
  assert.equal(r.modelCount, 3);
  assert.equal(r.status, 200);
  assert.match(r.message, /3 models visible, including Claude Opus 5\.5, Claude Sonnet 5\.5/);
  assert.match(f.seen[0].url, /^https:\/\/api\.anthropic\.com\/v1\/models\?/);
  const models = await adapter.listModels(CREDS, new AbortController().signal);
  assert.deepEqual(models.map((m) => m.id), ["claude-opus-5-5", "claude-sonnet-5-5", "other"]);
});

await test("adapter.testConnection reports a rejected key without echoing it", async () => {
  const f = fakeFetch(() => new Response(JSON.stringify({ type: "error", error: { type: "authentication_error", message: "invalid x-api-key sk-ant-test12345678" } }), { status: 401, headers: { "content-type": "application/json" } }));
  const r = await createAnthropicAdapter({ fetch: f, resolveHost: publicHost }).testConnection(CREDS);
  assert.equal(r.ok, false);
  assert.equal(r.status, 401);
  assert.doesNotMatch(r.message, /sk-ant-test12345678/);
});

/* ─── Dispatch: the credential rule ────────────────────────── */

function recordingAdapter(id) {
  const calls = [];
  return {
    id, capabilities: { leakRecovery: false, emptyTurnRetry: false }, calls,
    async call(req, ctx) { calls.push(ctx); return { provider: id, model: req.ref.model, text: ["ok"], thinking: [], toolCalls: [], finish: "stop", usage: null, leakedToolCallSuspected: false, raw: [] }; },
    async listModels() { return []; }, async testConnection() { return { ok: true, message: "" }; }, classifyError: (e) => e,
  };
}

await test("dispatch: a non-Google provider never receives the caller's Google credentials; it reads its own", async () => {
  const anthropic = recordingAdapter("anthropic");
  const asked = [];
  const deps = { adapters: { anthropic }, resolveCreds: async (p) => { asked.push(p); return { apiKey: "stored-anthropic-key", baseUrl: "https://gateway.example.com" }; } };
  const events = [];
  await dispatch.callModel(request(), { creds: { apiKey: "GOOGLE-KEY", serviceAccountJson: "{}" }, step: 3, onEvent: (e) => events.push(e) }, deps);
  assert.deepEqual(asked, ["anthropic"]);
  assert.deepEqual(anthropic.calls[0].creds, { apiKey: "stored-anthropic-key", baseUrl: "https://gateway.example.com" });
  assert.equal(anthropic.calls[0].step, 3);
  assert.equal(typeof anthropic.calls[0].onEvent, "function", "onEvent is passed through");
});

await test("dispatch: Vertex still receives the caller's credentials and never consults the store", async () => {
  const vertex = recordingAdapter("vertex");
  const deps = { adapters: { vertex }, resolveCreds: async () => { throw new Error("must not be called"); } };
  await dispatch.callModel(request({ ref: { provider: "vertex", model: "gemini-test" } }), { creds: { apiKey: "G" } }, deps);
  assert.deepEqual(vertex.calls[0].creds, { apiKey: "G" });
});

await test("dispatch: an unconfigured Claude provider fails with PROVIDER_NOT_CONFIGURED before any request", async () => {
  const anthropic = recordingAdapter("anthropic");
  await assert.rejects(
    dispatch.callModel(request(), { creds: { apiKey: "GOOGLE-KEY" } }, { adapters: { anthropic }, resolveCreds: async () => null }),
    (e) => e instanceof ProviderError && e.code === "PROVIDER_NOT_CONFIGURED" && /Anthropic/.test(e.message) && !/GOOGLE-KEY/.test(e.message),
  );
  assert.equal(anthropic.calls.length, 0);
});

await test("dispatch: the built-in registry resolves each provider to its own adapter and rejects an unknown one", () => {
  assert.equal(dispatch.resolveAdapter({ provider: "anthropic", model: "m" }).id, "anthropic");
  assert.equal(dispatch.resolveAdapter({ provider: "openai", model: "m" }).id, "openai");
  assert.equal(dispatch.resolveAdapter({ provider: "vertex", model: "m" }).id, "vertex");
  assert.throws(() => dispatch.resolveAdapter({ provider: "mistral", model: "m" }), (e) => e.code === "PROVIDER_NOT_CONFIGURED");
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall Anthropic mapping tests passed");
