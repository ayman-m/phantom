#!/usr/bin/env node
/**
 * The provider-neutral tool loop (lib/providers/turn-loop.ts) driven through
 * dispatch with a fake adapter, plus the same loop over the real Gemini
 * adapter with a stubbed fetch:
 *
 *   - tool loop: calls run, results go back, follow-ups use the turn's settings
 *   - directive ordering: a directive stays in place between results
 *   - call-id invariant: well-formed input is returned untouched; a missing
 *     result is filled at its call's position; extras and duplicates are logged
 *   - leak recovery and empty-turn retries, gated by the adapter's capability
 *     flags, bounded, and consuming loop turns as they always have
 *   - budget summary with tool choice 'none'
 *   - call ids stay unique across the turn (retries included)
 *   - thought signatures replay verbatim inside a turn
 *
 *   node scripts/test-route-loop-neutral.mjs   (npm run test:route-loop-neutral)
 */
import assert from "node:assert/strict";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const loop = await import("../lib/providers/turn-loop.ts");
const dispatch = await import("../lib/providers/dispatch.ts");
const { createGeminiAdapter } = await import("../lib/providers/gemini/adapter.ts");

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.message).split("\n").join("\n     ")); }
}

/* ─── Builders ──────────────────────────────────────────────── */

const REF = { provider: "vertex", model: "gemini-test" };
const TOOLS = [{ name: "xsiam.run_xql_query", description: "Run XQL", inputSchema: { type: "object", properties: { q: { type: "string" } } } },
  { name: "jobs_list", description: "List jobs", inputSchema: { type: "object" } }];

let seq = 0;
/** A neutral assistant turn. `calls` is [name, args]; ids follow the Gemini scheme. */
function turn({ text = [], thinking = [], calls = [], leaked = false, finish, raw, usage = null, step = seq++ } = {}) {
  return {
    provider: "vertex", model: REF.model, text, thinking,
    toolCalls: calls.map(([name, args], i) => ({ id: `gem_${step}_${i}`, name, args: args ?? {} })),
    finish: finish ?? (calls.length ? "tool_use" : "stop"),
    usage, leakedToolCallSuspected: leaked,
    raw: raw ?? [...text.map((t) => ({ text: t })), ...calls.map(([name, args]) => ({ functionCall: { name, args: args ?? {} } }))],
  };
}

const GEMINI_CAPS = { leakRecovery: true, emptyTurnRetry: true };
const NO_CAPS = { leakRecovery: false, emptyTurnRetry: false };

/** An adapter that serves scripted turns and records every request it saw. */
function fakeAdapter(script, capabilities = GEMINI_CAPS, extra = {}) {
  const seen = [];
  return {
    id: "vertex", capabilities, seen,
    async call(req, ctx) {
      seen.push({
        toolChoice: req.toolChoice, thinking: req.thinking, purpose: req.purpose, step: ctx.step,
        toolCount: req.tools.length, system: req.system, messages: structuredClone(req.messages),
      });
      const next = script.shift();
      if (!next) throw new Error("fake adapter: script exhausted");
      return typeof next === "function" ? next(req, ctx) : next;
    },
    async listModels() { return []; },
    async testConnection() { return { ok: true, message: "" }; },
    classifyError: (e) => e,
    ...extra,
  };
}

/** Run the loop over `adapter`. `exec` returns the tool results for a turn. */
async function runLoop({ adapter, initial, exec, hasText, maxTurns = 30, turnThinking = true, deps }) {
  const dispatchDeps = deps ?? { adapters: { vertex: adapter } };
  const messages = [{ role: "user", text: "hello" }];
  const events = { presented: [], followups: [], notes: [], warns: [] };
  let finalText = 0;
  const call = (msgs, o) => dispatch.callModel(
    { ref: REF, system: "SYSTEM", messages: msgs, tools: TOOLS, toolChoice: o.toolChoice, thinking: o.thinking,
      purpose: o.toolChoice === "none" ? "budget_summary" : "chat" },
    { creds: {}, step: o.step },
    dispatchDeps,
  );
  const result = await loop.runModelLoop({
    initial, messages, maxTurns, turnThinking,
    capabilities: dispatch.capabilitiesFor(REF, dispatchDeps),
    nextCallStep: 1,
    call,
    presentTurn: async (t, step) => { events.presented.push(step); finalText += t.text.length; },
    hasFinalText: hasText ?? (() => finalText > 0),
    executeToolCalls: exec ?? (async (t) => t.toolCalls.map((c) => ({ kind: "result", callId: c.id, name: c.name, payload: { result: `ok ${c.name}` } }))),
    onFollowup: (t) => events.followups.push(t),
    note: (m) => events.notes.push(m),
    warn: (m) => events.warns.push(m),
  });
  return { result, messages, events, call };
}

/* ─── The tool loop ─────────────────────────────────────────── */

await test("tool loop: results go back keyed by call id, then the model answers", async () => {
  const initial = turn({ text: ["Checking."], calls: [["xsiam.run_xql_query", { q: "x" }], ["jobs_list"]], step: 0 });
  const adapter = fakeAdapter([turn({ text: ["Done."], step: 1 })]);
  const { result, messages, events } = await runLoop({ adapter, initial });
  assert.equal(result.exhaustedBudget, false);
  assert.equal(result.lastTurn.text[0], "Done.");
  assert.equal(adapter.seen.length, 1);
  const sent = adapter.seen[0];
  assert.deepEqual(sent.messages.map((m) => m.role), ["user", "assistant_turn", "tool_results"]);
  assert.deepEqual(sent.messages[2].items.map((i) => [i.kind, i.callId, i.name]), [
    ["result", "gem_0_0", "xsiam.run_xql_query"], ["result", "gem_0_1", "jobs_list"],
  ]);
  assert.equal(sent.messages[1].turn.toolCalls[0].id, "gem_0_0");
  assert.equal(sent.toolChoice, "auto");
  assert.equal(sent.thinking, true, "a follow-up keeps the turn's thinking setting");
  assert.equal(sent.step, 1, "the first loop call follows the initial call (step 0)");
  assert.deepEqual(events.presented, [0, 1]);
  assert.equal(events.followups.length, 1);
  assert.deepEqual(messages.map((m) => m.role), ["user", "assistant_turn", "tool_results"]);
});

await test("tool loop: several rounds, every follow-up sees all earlier turns", async () => {
  const initial = turn({ calls: [["jobs_list"]], step: 0 });
  const adapter = fakeAdapter([turn({ calls: [["jobs_list"]], step: 1 }), turn({ text: ["Final."], step: 2 })]);
  const { messages } = await runLoop({ adapter, initial });
  assert.deepEqual(adapter.seen.map((s) => s.messages.length), [3, 5]);
  assert.deepEqual(adapter.seen.map((s) => s.step), [1, 2]);
  assert.equal(messages.length, 5);
});

await test("tool loop: thinking off is honoured on follow-ups when the turn says so", async () => {
  const initial = turn({ calls: [["jobs_list"]], step: 0 });
  const adapter = fakeAdapter([turn({ text: ["x"], step: 1 })]);
  await runLoop({ adapter, initial, turnThinking: false });
  assert.equal(adapter.seen[0].thinking, false);
});

await test("tool loop: the assistant turn is replayed through its raw payload", async () => {
  const raw = [{ text: "hm", thought: true, thoughtSignature: "c2ln" }, { functionCall: { name: "jobs_list", args: {} }, thoughtSignature: "c2ln2" }];
  const initial = turn({ thinking: ["hm"], calls: [["jobs_list"]], raw, step: 0 });
  const adapter = fakeAdapter([turn({ text: ["x"], step: 1 })]);
  await runLoop({ adapter, initial });
  assert.deepEqual(adapter.seen[0].messages[1].turn.raw, raw);
});

/* ─── Directive ordering and the call-id invariant ──────────── */

await test("directive ordering: a directive stays between the results it was pushed among", async () => {
  const calls = [["xsiam.run_xql_query"], ["jobs_list"]];
  const initial = turn({ calls, step: 0 });
  const items = [
    { kind: "result", callId: "gem_0_0", name: "xsiam.run_xql_query", payload: { result: "fail" } },
    { kind: "directive", text: "STOP retrying" },
    { kind: "result", callId: "gem_0_1", name: "jobs_list", payload: { result: "ok" } },
  ];
  const adapter = fakeAdapter([turn({ text: ["x"], step: 1 })]);
  const { messages, events } = await runLoop({ adapter, initial, exec: async () => items });
  assert.equal(messages[2].items, items, "same array object: nothing was copied or reordered");
  assert.deepEqual(adapter.seen[0].messages[2].items.map((i) => i.kind), ["result", "directive", "result"]);
  assert.deepEqual(events.warns, []);
});

await test("invariant: well-formed input is returned as the very same array", () => {
  const calls = [{ id: "a", name: "t1", args: {} }, { id: "b", name: "t2", args: {} }];
  const items = [
    { kind: "result", callId: "a", name: "t1", payload: { result: "1" } },
    { kind: "directive", text: "d" },
    { kind: "result", callId: "b", name: "t2", payload: { result: "2" } },
  ];
  const warns = [];
  assert.equal(loop.reconcileToolResults(calls, items, (m) => warns.push(m)), items);
  assert.deepEqual(warns, []);
  assert.equal(loop.reconcileToolResults([], [], () => {}).length, 0);
});

await test("invariant: a missing result is filled at its call's position and logged", () => {
  const calls = [0, 1, 2, 3].map((i) => ({ id: `c${i}`, name: `t${i}`, args: {} }));
  const r = (i) => ({ kind: "result", callId: `c${i}`, name: `t${i}`, payload: { result: String(i) } });
  const warns = [];
  const out = loop.reconcileToolResults(calls, [r(0), { kind: "directive", text: "d" }, r(3)], (m) => warns.push(m));
  assert.deepEqual(out.map((i) => (i.kind === "directive" ? "dir" : i.callId)), ["c0", "dir", "c1", "c2", "c3"]);
  assert.deepEqual(out[2], { kind: "result", callId: "c1", name: "t1", payload: { error: "no result recorded" } });
  assert.equal(warns.length, 2);
  assert.match(warns[0], /c1/);
  // Nothing recorded at all: every call gets one, in order.
  const none = loop.reconcileToolResults(calls, [], () => {});
  assert.deepEqual(none.map((i) => i.callId), ["c0", "c1", "c2", "c3"]);
  // The last call missing: appended.
  const tail = loop.reconcileToolResults(calls.slice(0, 2), [r(0)], () => {});
  assert.deepEqual(tail.map((i) => i.callId), ["c0", "c1"]);
});

await test("invariant: the caller's array is not mutated when a fill is needed", () => {
  const calls = [{ id: "a", name: "t", args: {} }];
  const items = [];
  const out = loop.reconcileToolResults(calls, items, () => {});
  assert.equal(items.length, 0);
  assert.equal(out.length, 1);
});

await test("invariant: extras and duplicates are logged and left in place, not dropped", () => {
  const calls = [{ id: "a", name: "t", args: {} }];
  const result = (callId) => ({ kind: "result", callId, name: "t", payload: { result: callId } });
  const items = [result("a"), result("a"), result("zzz")];
  const warns = [];
  const out = loop.reconcileToolResults(calls, items, (m) => warns.push(m));
  assert.equal(out, items);
  assert.equal(warns.length, 2);
  assert.ok(warns.some((m) => /unknown call id zzz/.test(m)));
  assert.ok(warns.some((m) => /call id a has 2 results/.test(m)));
});

await test("invariant: the loop applies it, so a tool path that forgot a result still sends one", async () => {
  const initial = turn({ calls: [["xsiam.run_xql_query"], ["jobs_list"]], step: 0 });
  const adapter = fakeAdapter([turn({ text: ["x"], step: 1 })]);
  const { events } = await runLoop({
    adapter, initial,
    exec: async (t) => [{ kind: "result", callId: t.toolCalls[0].id, name: t.toolCalls[0].name, payload: { result: "ok" } }],
  });
  const items = adapter.seen[0].messages[2].items;
  assert.deepEqual(items.map((i) => i.callId), ["gem_0_0", "gem_0_1"]);
  assert.deepEqual(items[1].payload, { error: "no result recorded" });
  assert.equal(events.warns.length, 1);
});

/* ─── Leak recovery and empty-turn retries ──────────────────── */

await test("leak recovery: retries with a forced call and thinking off, bounded at two", async () => {
  const leak = () => turn({ thinking: ["default_api.run(...)"], leaked: true });
  const initial = leak();
  const adapter = fakeAdapter([leak(), leak(), turn({ text: ["gave up"] })]);
  const { events, result } = await runLoop({ adapter, initial });
  assert.deepEqual(adapter.seen.slice(0, 2).map((s) => [s.toolChoice, s.thinking]), [["required", false], ["required", false]]);
  assert.equal(adapter.seen.length, 3, "two leak retries, then the empty-turn retry runs out the script");
  assert.ok(events.notes.some((n) => /attempt 1\/2/.test(n)));
  assert.ok(events.notes.some((n) => /attempt 2\/2/.test(n)));
  assert.ok(result);
});

await test("leak recovery: the retried turn is then processed normally (a forced call runs its tool)", async () => {
  const initial = turn({ thinking: ["default_api.jobs_list()"], leaked: true });
  const adapter = fakeAdapter([turn({ calls: [["jobs_list"]] }), turn({ text: ["listed"] })]);
  const { messages } = await runLoop({ adapter, initial });
  assert.equal(adapter.seen[0].toolChoice, "required");
  assert.equal(adapter.seen[1].toolChoice, "auto");
  assert.deepEqual(adapter.seen[0].messages.map((m) => m.role), ["user"], "the leaked turn was never added to the history");
  assert.deepEqual(messages.map((m) => m.role), ["user", "assistant_turn", "tool_results"]);
});

await test("leak recovery: off when the adapter does not declare it", async () => {
  const initial = turn({ thinking: ["default_api.x"], leaked: true, text: ["I answered"] });
  const adapter = fakeAdapter([], NO_CAPS);
  const { result } = await runLoop({ adapter, initial });
  assert.equal(adapter.seen.length, 0);
  assert.equal(result.exhaustedBudget, false);
});

await test("empty turn: first retry identical, second with thinking off, then stop", async () => {
  const adapter = fakeAdapter([turn(), turn()]);
  const { result, events } = await runLoop({ adapter, initial: turn(), turnThinking: true });
  assert.deepEqual(adapter.seen.map((s) => [s.toolChoice, s.thinking]), [["auto", true], ["auto", false]]);
  assert.equal(result.exhaustedBudget, false);
  assert.ok(events.notes.some((n) => /attempt 2\/2, thinking off/.test(n)));
});

await test("empty turn: no retry once any text exists this message", async () => {
  const adapter = fakeAdapter([]);
  const { result } = await runLoop({ adapter, initial: turn(), hasText: () => true });
  assert.equal(adapter.seen.length, 0);
  assert.equal(result.exhaustedBudget, false);
});

await test("empty turn: off when the adapter does not declare it", async () => {
  const adapter = fakeAdapter([], NO_CAPS);
  await runLoop({ adapter, initial: turn() });
  assert.equal(adapter.seen.length, 0);
});

await test("retries consume loop turns, as they always have", async () => {
  // maxTurns 2: the initial empty turn uses turn 0, its retry turn 1; a second retry is issued
  // but the loop ends before that retried turn is processed.
  const adapter = fakeAdapter([turn(), turn({ text: ["late"] })]);
  const { result, events } = await runLoop({ adapter, initial: turn(), maxTurns: 2 });
  assert.equal(result.exhaustedBudget, true);
  assert.equal(result.lastTurn.text[0], "late");
  assert.deepEqual(events.presented, [0, 1]);
});

/* ─── Budget exhaustion and the summary ─────────────────────── */

await test("budget exhaustion: the last turn is handed back unprocessed", async () => {
  const initial = turn({ calls: [["jobs_list"]], step: 0 });
  const adapter = fakeAdapter([turn({ text: ["the deliverable"], calls: [["jobs_list"]], step: 1 })]);
  const { result, events } = await runLoop({ adapter, initial, maxTurns: 1 });
  assert.equal(result.exhaustedBudget, true);
  assert.deepEqual(result.lastTurn.text, ["the deliverable"]);
  assert.deepEqual(events.presented, [0], "turn 1 was never presented");
  assert.equal(result.nextCallStep, 2);
});

await test("budget summary: pushes the prompt, asks with tool choice none and thinking off", async () => {
  const adapter = fakeAdapter([turn({ text: ["Summary."] })]);
  const messages = [{ role: "user", text: "q" }, { role: "assistant_turn", turn: turn({ calls: [["jobs_list"]] }) },
    { role: "tool_results", items: [] }];
  const call = (msgs, o) => dispatch.callModel(
    { ref: REF, system: "S", messages: msgs, tools: TOOLS, toolChoice: o.toolChoice, thinking: o.thinking, purpose: "budget_summary" },
    { creds: {}, step: o.step }, { adapters: { vertex: adapter } });
  const summary = await loop.requestBudgetSummary({ messages, call, step: 7 });
  assert.deepEqual(summary.text, ["Summary."]);
  const sent = adapter.seen[0];
  assert.equal(sent.toolChoice, "none");
  assert.equal(sent.thinking, false);
  assert.equal(sent.purpose, "budget_summary");
  assert.equal(sent.step, 7);
  assert.equal(sent.toolCount, 2, "the tools stay in the request; the adapter decides how to honour 'none'");
  assert.deepEqual(sent.messages.at(-1), { role: "user", text: loop.BUDGET_SUMMARY_PROMPT });
  assert.deepEqual(sent.messages.map((m) => m.role), ["user", "assistant_turn", "tool_results", "user"]);
  assert.match(loop.BUDGET_SUMMARY_PROMPT, /^Tool budget reached\. Summarize your findings so far for the operator, even if the investigation is incomplete\. Do not call any more tools\.$/);
});

/* ─── Dispatch ──────────────────────────────────────────────── */

await test("dispatch: capabilities come from the adapter", () => {
  assert.deepEqual(dispatch.capabilitiesFor(REF, { adapters: { vertex: fakeAdapter([], NO_CAPS) } }), NO_CAPS);
  assert.deepEqual(dispatch.capabilitiesFor(REF), { leakRecovery: true, emptyTurnRetry: true }, "the built-in Gemini adapter");
});

await test("dispatch: the tools estimate falls back to the neutral specs for an adapter with no rendering", () => {
  const plain = fakeAdapter([]);
  assert.equal(dispatch.estimateToolsJson(REF, TOOLS, { adapters: { vertex: plain } }), JSON.stringify(TOOLS));
  const custom = fakeAdapter([], GEMINI_CAPS, { estimateToolsPayload: (t) => ({ n: t.length }) });
  assert.equal(dispatch.estimateToolsJson(REF, TOOLS, { adapters: { vertex: custom } }), '{"n":2}');
});

/* ─── The same loop over the real Gemini adapter ────────────── */

function geminiResponse(parts, finishReason = "STOP") {
  return { candidates: [{ content: { role: "model", parts }, finishReason }], usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 2 } };
}

function geminiWorld(responses) {
  const requests = [];
  const queue = responses.slice();
  const deps = {
    fetch: async (url, init) => {
      requests.push({ url, body: JSON.parse(init.body), raw: init.body });
      const body = queue.shift();
      if (!body) throw new Error("no scripted Gemini response left");
      return { ok: true, status: 200, text: async () => JSON.stringify(body), json: async () => structuredClone(body) };
    },
    retry: { sleep: async () => {}, random: () => 0 },
  };
  return { requests, dispatchDeps: { adapters: { vertex: createGeminiAdapter(deps) } } };
}

async function geminiLoop({ responses, exec, maxTurns = 30 }) {
  const world = geminiWorld(responses);
  let finalText = 0;
  const messages = [{ role: "user", text: "go" }];
  const callWith = (msgs, o) => dispatch.callModel(
    { ref: REF, system: "SYS", messages: msgs, tools: TOOLS, toolChoice: o.toolChoice, thinking: o.thinking,
      purpose: o.toolChoice === "none" ? "budget_summary" : "chat" },
    { creds: { apiKey: "FAKE-KEY" }, step: o.step }, world.dispatchDeps);
  const initial = await callWith(messages, { step: 0, thinking: true, toolChoice: "auto" });
  const result = await loop.runModelLoop({
    initial, messages, maxTurns, turnThinking: true,
    capabilities: dispatch.capabilitiesFor(REF, world.dispatchDeps), nextCallStep: 1, call: callWith,
    presentTurn: async (t) => { finalText += t.text.length; },
    hasFinalText: () => finalText > 0,
    executeToolCalls: exec ?? (async (t) => t.toolCalls.map((c) => ({ kind: "result", callId: c.id, name: c.name, payload: { result: "ok" } }))),
    onFollowup: () => {},
  });
  return { world, result, messages, callWith };
}

await test("gemini: signatures replay verbatim and results are matched by position, directive in place", async () => {
  const parts = [
    { text: "thinking it over", thought: true, thoughtSignature: "SIG-1" },
    { functionCall: { name: "xsiam.run_xql_query", args: { q: "x" } }, thoughtSignature: "SIG-2" },
    { functionCall: { name: "jobs_list", args: {} } },
  ];
  const { world } = await geminiLoop({
    responses: [geminiResponse(parts), geminiResponse([{ text: "done" }])],
    exec: async (t) => [
      { kind: "result", callId: t.toolCalls[0].id, name: t.toolCalls[0].name, payload: { result: "r1" } },
      { kind: "directive", text: "STOP" },
      { kind: "result", callId: t.toolCalls[1].id, name: t.toolCalls[1].name, payload: { result: "r2" } },
    ],
  });
  const follow = world.requests[1].body;
  assert.deepEqual(follow.contents[1], { role: "model", parts });
  assert.deepEqual(follow.contents[2].parts, [
    { functionResponse: { name: "xsiam.run_xql_query", response: { result: "r1" } } },
    { functionResponse: { name: "__system_stop_directive__", response: { stop_directive: "STOP" } } },
    { functionResponse: { name: "jobs_list", response: { result: "r2" } } },
  ]);
  assert.deepEqual(Object.keys(follow), ["contents", "tools", "systemInstruction", "generationConfig"]);
  assert.ok(!JSON.stringify(follow).includes("gem_"), "call ids never reach the Gemini wire");
});

await test("gemini: call ids stay unique across the turn, retries included", async () => {
  const call = (n) => geminiResponse([{ functionCall: { name: "jobs_list", args: { n } } }]);
  const { messages } = await geminiLoop({
    // call, an empty follow-up (retried), a second call, then the answer.
    responses: [call(1), geminiResponse([]), call(2), geminiResponse([{ text: "end" }])],
  });
  const ids = messages.filter((m) => m.role === "assistant_turn").flatMap((m) => m.turn.toolCalls.map((c) => c.id));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(ids.length, 2);
});

await test("gemini: leak recovery sends a forced call with thinking off, then the turn carries on", async () => {
  const leaked = geminiResponse([{ text: "default_api.jobs_list()", thought: true }]);
  const forced = geminiResponse([{ functionCall: { name: "jobs_list", args: {} } }]);
  const { world } = await geminiLoop({ responses: [leaked, forced, geminiResponse([{ text: "listed" }])] });
  const retry = world.requests[1].body;
  assert.deepEqual(retry.toolConfig, { functionCallingConfig: { mode: "ANY" } });
  assert.equal(retry.generationConfig, undefined, "thinking is off on the retry");
  assert.equal(retry.contents.length, 1, "the leaked turn is not in the history");
  assert.equal(world.requests[2].body.generationConfig.thinkingConfig.thinkingBudget, -1, "thinking is back on for the follow-up");
});

await test("gemini: budget exhaustion then summary sends tools: [] with the full history", async () => {
  const call = geminiResponse([{ functionCall: { name: "jobs_list", args: {} } }]);
  const { world, result, messages, callWith } = await geminiLoop({
    responses: [call, call, geminiResponse([{ text: "Summary text" }])], maxTurns: 1,
  });
  assert.equal(result.exhaustedBudget, true);
  const summary = await loop.requestBudgetSummary({ messages, call: callWith, step: result.nextCallStep });
  assert.deepEqual(summary.text, ["Summary text"]);
  const body = world.requests.at(-1).body;
  assert.deepEqual(body.tools, []);
  assert.equal(body.generationConfig, undefined);
  assert.equal(body.toolConfig, undefined);
  assert.deepEqual(body.contents.at(-1), { role: "user", parts: [{ text: loop.BUDGET_SUMMARY_PROMPT }] });
  assert.deepEqual(body.contents.slice(-2, -1)[0].role, "user", "two user contents in a row, not merged");
  assert.ok(world.requests[0].body.tools[0].functionDeclarations.length === 2, "the normal requests carry the catalog");
});

await test("gemini: the tool catalog is rendered once per spec, not once per call", async () => {
  const { world } = await geminiLoop({
    responses: [geminiResponse([{ functionCall: { name: "jobs_list", args: {} } }]), geminiResponse([{ text: "x" }])],
  });
  assert.equal(world.requests[0].body.tools[0].functionDeclarations.length, 2);
  assert.equal(JSON.stringify(world.requests[0].body.tools), JSON.stringify(world.requests[1].body.tools));
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
