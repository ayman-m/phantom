#!/usr/bin/env node
/**
 * SSE reading and Messages-stream assembly (lib/providers/sse.ts,
 * lib/providers/anthropic/stream.ts) against synthetic recordings in
 * scripts/fixtures/anthropic-sse/ built from the documented event shapes:
 * ping, text/thinking/signature/input_json deltas, cumulative usage, a
 * mid-stream error, CRLF line endings and a last event with no blank line.
 *
 * Every recording is replayed at several chunk sizes (down to one byte, which
 * splits multibyte characters and CRLF pairs) and must assemble identically.
 *
 *   node scripts/test-provider-sse.mjs   (npm run test:provider-sse)
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

const { createSseParser, readSse } = await import("../lib/providers/sse.ts");
const { createStreamAssembler, readAnthropicStream, mapAnthropicUsage, mergeUsage } = await import(
  "../lib/providers/anthropic/stream.ts"
);
const { ProviderError } = await import("../lib/providers/errors.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "anthropic-sse");
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

async function assemble(name, size) {
  return await readAnthropicStream(streamOf(fixture(name), size));
}

const SIZES = [1, 3, 7, 64, 100000];

/* ─── SSE parser ───────────────────────────────────────────── */

await test("parser: LF, CRLF and bare CR line ends all dispatch the same events", () => {
  for (const eol of ["\n", "\r\n", "\r"]) {
    const p = createSseParser();
    const text = ["event: a", "data: 1", "", "event: b", "data: 2", "", ""].join(eol);
    const events = [...p.push(text), ...p.flush()];
    assert.deepEqual(events, [{ event: "a", data: "1" }, { event: "b", data: "2" }], JSON.stringify(eol));
  }
});

await test("parser: a CRLF split between chunks is one line end, not two", () => {
  const p = createSseParser();
  const out = [...p.push("data: x\r"), ...p.push("\n\r"), ...p.push("\ndata: y\n\n"), ...p.flush()];
  assert.deepEqual(out, [{ data: "x" }, { data: "y" }]);
});

await test("parser: multi-line data joins with newline, comments and unknown fields are ignored", () => {
  const p = createSseParser();
  const out = [...p.push(": keepalive\nretry: 100\nid: 7\nevent: m\ndata: one\ndata:two\ndata\n\n"), ...p.flush()];
  assert.deepEqual(out, [{ event: "m", data: "one\ntwo\n", id: "7" }]);
});

await test("parser: an event with no data line is not dispatched; a leading BOM is dropped", () => {
  const p = createSseParser();
  const out = [...p.push("﻿event: ping\n\ndata: ok\n\n"), ...p.flush()];
  assert.deepEqual(out, [{ data: "ok" }]);
});

await test("parser: flush dispatches a last event that lacks its blank line", () => {
  const p = createSseParser();
  assert.deepEqual(p.push("data: tail"), []);
  assert.deepEqual(p.flush(), [{ data: "tail" }]);
});

await test("parser: an oversized event is refused", () => {
  const p = createSseParser({ maxEventBytes: 50 });
  assert.throws(() => p.push("data: " + "x".repeat(200) + "\n"), /larger than/);
  const q = createSseParser({ maxEventBytes: 50 });
  assert.throws(() => q.push("data: " + "x".repeat(200)), /larger than/);
});

await test("readSse: bytes split inside a multibyte character still decode", async () => {
  const bytes = new TextEncoder().encode("data: wörld ✓ \u{1F512}\n\n");
  for (const size of [1, 2, 5]) {
    const got = [];
    for await (const ev of readSse(streamOf(bytes, size))) got.push(ev.data);
    assert.deepEqual(got, ["wörld ✓ \u{1F512}"], `size ${size}`);
  }
});

await test("readSse: onChunk fires for every network chunk, including comment-only ones", async () => {
  let chunks = 0;
  const bytes = new TextEncoder().encode(": ping\n\n: ping\n\ndata: a\n\n");
  for await (const _ of readSse(streamOf(bytes, 4), { onChunk: () => { chunks += 1; } })) { /* drain */ }
  assert.equal(chunks, Math.ceil(bytes.length / 4));
});

/* ─── Assembly ─────────────────────────────────────────────── */

await test("text-only: assembles at every chunk size, ping and comments ignored, last event without blank line", async () => {
  for (const size of SIZES) {
    const m = await assemble("text-only.sse", size);
    assert.deepEqual(m.content, [{ type: "text", text: "Hello, wörld ✓ \u{1F512}" }], `size ${size}`);
    assert.equal(m.stopReason, "end_turn");
    assert.equal(m.id, "msg_01TextOnly");
  }
});

await test("usage: message_start seeds the totals and the cumulative message_delta is not summed", async () => {
  const m = await assemble("text-only.sse", 64);
  assert.equal(m.usage.input_tokens, 25);
  assert.equal(m.usage.cache_read_input_tokens, 900);
  assert.equal(m.usage.output_tokens, 15, "max(1, 15), never 16");
  assert.deepEqual(mapAnthropicUsage(m.usage), {
    inputTotal: 25 + 100 + 900,
    cacheRead: 900,
    cacheWrite: 100,
    cacheWrite1h: 40,
    output: 15,
    reasoning: 0,
  });
});

await test("usage: message_delta carrying the full cumulative counts does not double them", async () => {
  const m = await assemble("tool-use-crlf.sse", 64);
  assert.deepEqual(mapAnthropicUsage(m.usage), {
    inputTotal: 30 + 0 + 2000,
    cacheRead: 2000,
    cacheWrite: 0,
    cacheWrite1h: 0,
    output: 210,
    reasoning: 0,
  });
});

await test("mapAnthropicUsage: missing usage is null; only a tier breakdown still yields the write total", () => {
  assert.equal(mapAnthropicUsage(undefined), null);
  assert.equal(mapAnthropicUsage({}), null);
  const u = mapAnthropicUsage({ input_tokens: 5, output_tokens: 7, cache_creation: { ephemeral_5m_input_tokens: 10, ephemeral_1h_input_tokens: 20 } });
  assert.deepEqual(u, { inputTotal: 35, cacheRead: 0, cacheWrite: 30, cacheWrite1h: 20, output: 7, reasoning: 0 });
});

await test("mergeUsage: numbers take the max, nested objects merge, nulls are ignored", () => {
  const t = { input_tokens: 5, cache_creation: { ephemeral_5m_input_tokens: 3 } };
  mergeUsage(t, { input_tokens: 2, output_tokens: 9, cache_creation: { ephemeral_5m_input_tokens: 4, ephemeral_1h_input_tokens: 1 }, service_tier: null });
  assert.deepEqual(t, { input_tokens: 5, output_tokens: 9, cache_creation: { ephemeral_5m_input_tokens: 4, ephemeral_1h_input_tokens: 1 } });
});

await test("tool-use (CRLF): thinking, signature, redacted thinking and partial-JSON input assemble at every chunk size", async () => {
  for (const size of SIZES) {
    const m = await assemble("tool-use-crlf.sse", size);
    assert.equal(m.content.length, 5, `size ${size}`);
    assert.deepEqual(m.content[0], {
      type: "thinking",
      thinking: "Need the events table.",
      signature: "EqoBCkgIARABGAIiQ-SYNTHETIC-SIGNATURE==",
    });
    assert.deepEqual(m.content[1], { type: "redacted_thinking", data: "EmwKAhgBEgyhUnVzdGVkLVNZTlRIRVRJQw==" });
    assert.deepEqual(m.content[2], { type: "text", text: "Let me check." });
    assert.deepEqual(m.content[3], {
      type: "tool_use",
      id: "toolu_01SyntheticA",
      name: "xsiam__run_xql_query",
      input: { query: "dataset = x | limit 5", limit: 5 },
    });
    assert.deepEqual(m.content[4], { type: "tool_use", id: "toolu_01SyntheticB", name: "memory_search", input: {} }, "empty buffer is {}");
    assert.equal(m.stopReason, "tool_use");
  }
});

await test("a truncated tool_use (output cut mid-JSON) is dropped and reported; the text survives", async () => {
  const m = await assemble("truncated-tool.sse", 5);
  assert.deepEqual(m.content, [{ type: "text", text: "Running it." }]);
  assert.deepEqual(m.truncatedToolCalls, [{ id: "toolu_01Cut", name: "xsiam__run_xql_query" }]);
  assert.equal(m.stopReason, "max_tokens");
});

await test("refusal and context-window stop reasons arrive with their details", async () => {
  const r = await assemble("refusal.sse", 9);
  assert.equal(r.stopReason, "refusal");
  assert.deepEqual(r.stopDetails, { category: "example-category", explanation: "synthetic refusal" });
  assert.deepEqual(r.content, []);
  const c = await assemble("context-exceeded.sse", 9);
  assert.equal(c.stopReason, "model_context_window_exceeded");
  assert.deepEqual(c.content, [{ type: "text", text: "Cut short" }]);
});

await test("a mid-stream error event throws a retryable overloaded ProviderError", async () => {
  for (const size of [3, 100000]) {
    await assert.rejects(assemble("mid-stream-error.sse", size), (err) => {
      assert.ok(err instanceof ProviderError);
      assert.equal(err.kind, "overloaded");
      assert.equal(err.retryable, true);
      assert.match(err.message, /Overloaded/);
      return true;
    });
  }
});

await test("a stream that ends before message_stop is a retryable network error", async () => {
  await assert.rejects(assemble("no-message-stop.sse", 11), (err) => {
    assert.ok(err instanceof ProviderError);
    assert.equal(err.kind, "network");
    assert.equal(err.retryable, true);
    assert.match(err.message, /before message_stop/);
    return true;
  });
});

await test("malformed data is a retryable network error and never echoes the payload", () => {
  const a = createStreamAssembler();
  assert.throws(() => a.push({ event: "content_block_delta", data: "{not json sk-ant-test12345678" }), (err) => {
    assert.ok(err instanceof ProviderError);
    assert.equal(err.retryable, true);
    assert.doesNotMatch(err.message, /sk-ant|not json/);
    return true;
  });
});

await test("a delta for a block that never started is a malformed-stream error", () => {
  const a = createStreamAssembler();
  assert.throws(() => a.push({ data: JSON.stringify({ type: "content_block_delta", index: 3, delta: { type: "text_delta", text: "x" } }) }), /malformed/);
});

await test("unknown event and delta types are skipped; unknown block types survive verbatim", () => {
  const a = createStreamAssembler();
  const send = (obj) => a.push({ data: JSON.stringify(obj) });
  send({ type: "message_start", message: { id: "m", usage: { input_tokens: 1, output_tokens: 1 } } });
  send({ type: "future_event", x: 1 });
  send({ type: "content_block_start", index: 0, content_block: { type: "server_tool_use", id: "srv_1", name: "web_search", input: { q: "x" }, extra: true } });
  send({ type: "content_block_delta", index: 0, delta: { type: "brand_new_delta", z: 1 } });
  send({ type: "content_block_stop", index: 0 });
  send({ type: "message_delta", delta: { stop_reason: "pause_turn" }, usage: { output_tokens: 4 } });
  send({ type: "message_stop" });
  const m = a.finish();
  assert.deepEqual(m.content, [{ type: "server_tool_use", id: "srv_1", name: "web_search", input: { q: "x" }, extra: true }]);
  assert.equal(m.stopReason, "pause_turn");
});

await test("blank text blocks are dropped from the replayable content", () => {
  const a = createStreamAssembler();
  const send = (obj) => a.push({ data: JSON.stringify(obj) });
  send({ type: "message_start", message: { id: "m", usage: { input_tokens: 1 } } });
  send({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } });
  send({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text: " \n" } });
  send({ type: "content_block_stop", index: 0 });
  send({ type: "content_block_start", index: 1, content_block: { type: "thinking", thinking: "" } });
  send({ type: "content_block_delta", index: 1, delta: { type: "signature_delta", signature: "sig" } });
  send({ type: "content_block_stop", index: 1 });
  send({ type: "message_delta", delta: { stop_reason: "end_turn" } });
  send({ type: "message_stop" });
  // An empty thinking block must still be replayed (the API requires the signature).
  assert.deepEqual(a.finish().content, [{ type: "thinking", thinking: "", signature: "sig" }]);
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall provider SSE tests passed");
