#!/usr/bin/env node
/**
 * Responses-stream assembly (lib/providers/openai/stream.ts) against synthetic
 * recordings in scripts/fixtures/openai-sse/ built from the documented event
 * names: text with a multibyte character, reasoning plus a function call,
 * parallel calls with no output array on the terminal event, a delta-only
 * stream, a refusal, an incomplete response with a cut-off call, response.failed,
 * a mid-stream error event and a stream with no terminal event.
 *
 * Every recording is replayed at several chunk sizes (down to one byte, which
 * splits multibyte characters and CRLF pairs) and must assemble identically.
 *
 * The per-event field names (item_id, output_index, content_index) are not yet
 * confirmed against live traffic; the first half of the assertions below show
 * the assembly does not depend on them.
 *
 *   node scripts/test-provider-openai-sse.mjs   (npm run test:provider-openai-sse)
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

const { createStreamAssembler, readOpenAiStream, mapOpenAiUsage, parseCallArguments } = await import(
  "../lib/providers/openai/stream.ts"
);
const { ProviderError } = await import("../lib/providers/errors.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "openai-sse");
const fixture = (name) => readFileSync(join(fixtureDir, name));

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

/** A byte stream that delivers `bytes` in pieces of `size`. */
function streamOf(bytes, size) {
  let at = 0;
  return new ReadableStream({
    pull(controller) {
      if (at >= bytes.length) { controller.close(); return; }
      controller.enqueue(new Uint8Array(bytes.subarray(at, Math.min(bytes.length, at + size))));
      at += size;
    },
  });
}

const assemble = (name, size, transform) => {
  const bytes = transform ? Buffer.from(transform(fixture(name).toString("utf8"))) : fixture(name);
  return readOpenAiStream(streamOf(bytes, size));
};
const SIZES = [1, 3, 7, 64, 100000];

async function rejection(promise) {
  try { await promise; } catch (e) { return e; }
  assert.fail("expected a rejection");
}

/* ─── Text and usage ───────────────────────────────────────── */

await test("text-only: the output items, status, ids and usage come through whole", async () => {
  const r = await assemble("text-only.sse", 100000);
  assert.equal(r.status, "completed");
  assert.equal(r.id, "resp_fixture_1");
  assert.equal(r.model, "gpt-6-sol");
  assert.equal(r.items.length, 1);
  assert.equal(r.items[0].content[0].text, "Scan ready — 3 hosts.");
  assert.deepEqual(r.truncatedToolCalls, []);
  assert.deepEqual(mapOpenAiUsage(r.usage), { inputTotal: 1200, cacheRead: 1024, cacheWrite: 0, cacheWrite1h: 0, output: 90, reasoning: 40 });
});

await test("every recording assembles identically at every chunk size, and with CRLF line ends", async () => {
  for (const name of ["text-only.sse", "tool-call.sse", "parallel-calls-no-output.sse", "deltas-only.sse", "refusal.sse", "incomplete-truncated-call.sse"]) {
    const reference = await assemble(name, 100000);
    for (const size of SIZES) {
      assert.deepEqual(await assemble(name, size), reference, `${name} at ${size} bytes`);
      assert.deepEqual(await assemble(name, size, (t) => t.replace(/\n/g, "\r\n")), reference, `${name} CRLF at ${size} bytes`);
    }
  }
});

/* ─── Reasoning, tool calls ────────────────────────────────── */

await test("tool-call: reasoning keeps its encrypted_content and summary; the call keeps its call_id and raw arguments", async () => {
  const r = await assemble("tool-call.sse", 5);
  assert.deepEqual(r.items.map((i) => i.type), ["reasoning", "function_call"]);
  assert.equal(r.items[0].encrypted_content, "ENC_BLOB_1");
  assert.equal(r.items[0].summary[0].text, "Need the open ports first.");
  assert.equal(r.items[1].call_id, "call_abc");
  assert.equal(r.items[1].arguments, '{"query":"dataset = x | limit 1"}');
  assert.deepEqual(mapOpenAiUsage(r.usage), { inputTotal: 1200, cacheRead: 1024, cacheWrite: 0, cacheWrite1h: 0, output: 140, reasoning: 90 });
});

await test("a terminal event with no output array: the items come from output_item.done, in output order even when the done events arrive out of order", async () => {
  const r = await assemble("parallel-calls-no-output.sse", 11);
  assert.deepEqual(r.items.map((i) => i.id), ["msg_p", "fc_a", "fc_b"]);
  assert.equal(r.items[2].call_id, "call_b");
  assert.equal(r.items[1].arguments, '{"query":"kerberos"}', "the final item, not the empty one from output_item.added");
});

await test("a stream with neither .done events nor an output array is rebuilt from its deltas", async () => {
  const r = await assemble("deltas-only.sse", 9);
  assert.deepEqual(r.items.map((i) => i.type), ["message", "function_call"]);
  assert.equal(r.items[0].content[0].text, "Rebuilt from deltas.");
  assert.equal(r.items[1].arguments, '{"query":"x"}');
  assert.deepEqual(parseCallArguments(r.items[1].arguments), { query: "x" });
});

await test("the output array of the terminal event wins over what the .done events said", () => {
  const a = createStreamAssembler();
  const push = (type, data) => a.push({ data: JSON.stringify({ type, ...data }) });
  push("response.output_item.done", { output_index: 0, item: { id: "msg_old", type: "message", content: [{ type: "output_text", text: "old" }] } });
  push("response.completed", { response: { status: "completed", output: [{ id: "msg_new", type: "message", content: [{ type: "output_text", text: "new" }] }] } });
  assert.deepEqual(a.finish().items.map((i) => i.id), ["msg_new"]);
});

await test("a delta that names no known item is ignored; bookkeeping fields are optional", () => {
  const a = createStreamAssembler();
  const push = (type, data) => a.push({ data: JSON.stringify({ type, ...data }) });
  push("response.output_text.delta", { item_id: "nope", output_index: 9, delta: "lost" });
  push("response.function_call_arguments.delta", { delta: "{}" });
  push("response.output_item.done", { item: { id: "msg_1", type: "message", content: [{ type: "output_text", text: "kept" }] } });
  push("response.completed", { response: { status: "completed" } });
  const r = a.finish();
  assert.equal(r.items.length, 1);
  assert.equal(r.items[0].content[0].text, "kept");
});

/* ─── Truncation, refusal, incomplete ──────────────────────── */

await test("incomplete + max_output_tokens: the cut-off call is dropped from the items and reported; reasoning stays", async () => {
  const r = await assemble("incomplete-truncated-call.sse", 13);
  assert.equal(r.status, "incomplete");
  assert.equal(r.incompleteReason, "max_output_tokens");
  assert.deepEqual(r.items.map((i) => i.type), ["reasoning"], "a function_call without valid arguments is never replayed");
  assert.deepEqual(r.truncatedToolCalls, [{ id: "call_cut", name: "xsiam__run_xql_query" }]);
});

await test("a call with empty or absent arguments is an empty object, not truncated", () => {
  assert.deepEqual(parseCallArguments(""), {});
  assert.deepEqual(parseCallArguments("  "), {});
  assert.deepEqual(parseCallArguments(undefined), {});
  assert.deepEqual(parseCallArguments({ a: 1 }), { a: 1 });
  assert.equal(parseCallArguments("[1]"), null);
  assert.equal(parseCallArguments('{"a":'), null);
  assert.equal(parseCallArguments(5), null);
});

await test("refusal: the refusal part survives in the item", async () => {
  const r = await assemble("refusal.sse", 100000);
  assert.deepEqual(r.items[0].content, [{ type: "refusal", refusal: "I can't help with that request." }]);
});

await test("response.incomplete without a status field still reads as incomplete", () => {
  const a = createStreamAssembler();
  a.push({ data: JSON.stringify({ type: "response.incomplete", response: { incomplete_details: { reason: "content_filter" } } }) });
  const r = a.finish();
  assert.equal(r.status, "incomplete");
  assert.equal(r.incompleteReason, "content_filter");
});

/* ─── Failure ──────────────────────────────────────────────── */

await test("response.failed throws the mapped error (server_error is retryable)", async () => {
  const err = await rejection(assemble("failed.sse", 100000));
  assert.ok(err instanceof ProviderError);
  assert.equal(err.kind, "unavailable");
  assert.equal(err.retryable, true);
  assert.match(err.message, /server had an error/);
});

await test("response.failed with a context overflow is context_exceeded and not retryable", async () => {
  const err = await rejection(assemble("context-exceeded.sse", 100000));
  assert.equal(err.kind, "context_exceeded");
  assert.equal(err.retryable, false);
});

await test("a mid-stream error event throws: rate_limit_exceeded is a retryable rate_limit", async () => {
  const err = await rejection(assemble("mid-stream-error.sse", 100000));
  assert.equal(err.kind, "rate_limit");
  assert.equal(err.retryable, true);
});

await test("a stream that ends with no terminal event is a retryable broken stream", async () => {
  const err = await rejection(assemble("no-terminal.sse", 100000));
  assert.ok(err instanceof ProviderError);
  assert.equal(err.kind, "network");
  assert.equal(err.retryable, true);
  assert.match(err.message, /ended before response\.completed/);
});

await test("data that is not JSON is a retryable broken stream; [DONE] is ignored; unknown events are skipped", () => {
  const a = createStreamAssembler();
  a.push({ data: "[DONE]" });
  a.push({ data: JSON.stringify({ type: "response.something_new", x: 1 }) });
  a.push({ data: JSON.stringify([1, 2]) });
  assert.equal(a.done, false);
  let thrown;
  try { a.push({ data: "<html>" }); } catch (e) { thrown = e; }
  assert.ok(thrown instanceof ProviderError);
  assert.equal(thrown.retryable, true);
});

await test("the event name on the SSE line is the fallback when the data has no type", () => {
  const a = createStreamAssembler();
  a.push({ event: "response.completed", data: JSON.stringify({ response: { status: "completed", output: [] } }) });
  assert.equal(a.done, true);
  assert.equal(a.finish().status, "completed");
});

/* ─── Usage ────────────────────────────────────────────────── */

await test("usage maps the cached, cache-write and reasoning details; missing or empty usage is null", () => {
  assert.deepEqual(
    mapOpenAiUsage({ input_tokens: 5000, input_tokens_details: { cached_tokens: 3000, cache_write_tokens: 500 }, output_tokens: 700, output_tokens_details: { reasoning_tokens: 600 } }),
    { inputTotal: 5000, cacheRead: 3000, cacheWrite: 500, cacheWrite1h: 0, output: 700, reasoning: 600 },
  );
  assert.deepEqual(mapOpenAiUsage({ input_tokens: 10, output_tokens: 2 }), { inputTotal: 10, cacheRead: 0, cacheWrite: 0, cacheWrite1h: 0, output: 2, reasoning: 0 });
  assert.equal(mapOpenAiUsage({}), null);
  assert.equal(mapOpenAiUsage(undefined), null);
  assert.deepEqual(mapOpenAiUsage({ input_tokens: -5, input_tokens_details: { cached_tokens: "x" }, output_tokens: NaN }), { inputTotal: 0, cacheRead: 0, cacheWrite: 0, cacheWrite1h: 0, output: 0, reasoning: 0 });
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall OpenAI SSE tests passed");
