#!/usr/bin/env node
/**
 * Closing the browser cancels the model call.
 *
 *   - isAbortedError tells a cancelled call from a provider failure;
 *   - the Gemini adapter hands the caller's signal to fetch, throws a neutral
 *     ABORTED error when it fires mid-request (and before any request when it
 *     already fired), and adds no `signal` to the request when none was given;
 *   - dispatch.callModel / summarizeText pass the signal to the adapter;
 *   - every model-call site in the chat route passes the turn's signal (or the
 *     slash context's), and the route ends an aborted turn without an error
 *     event or a failure audit row.
 *
 * The route itself is too wired to Next and the MCP to import here, so its
 * part is a source check that pins each call site, the wiring of the turn's
 * one signal (the request's abort AND the response stream's cancel) and each
 * quiet-abort branch. It does not exercise a real client disconnect.
 *
 *   node scripts/test-chat-abort.mjs   (npm run test:chat-abort)
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

const errors = await import("../lib/providers/errors.ts");
const dispatch = await import("../lib/providers/dispatch.ts");
const { createTurnAbort } = await import("../lib/turn-abort.ts");
const { createGeminiAdapter } = await import("../lib/providers/gemini/adapter.ts");

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

const REF = { provider: "vertex", model: "gemini-test" };
const REQ = { ref: REF, system: "S", messages: [{ role: "user", text: "hi" }], tools: [], toolChoice: "none", thinking: false, purpose: "chat" };
const OK_BODY = { candidates: [{ content: { parts: [{ text: "ok" }] }, finishReason: "STOP" }], usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1 } };

/** A fetch that records its init and either answers or hangs until the request's signal fires. */
function fakeFetch({ hang = false } = {}) {
  const calls = [];
  const fetch = (url, init) => {
    calls.push({ url: String(url), init });
    if (!hang) return Promise.resolve({ ok: true, status: 200, text: async () => "", json: async () => structuredClone(OK_BODY) });
    return new Promise((_, reject) => {
      init.signal.addEventListener("abort", () => reject(Object.assign(new Error("This operation was aborted"), { name: "AbortError" })), { once: true });
    });
  };
  return { fetch, calls };
}
const geminiCall = (deps, signal) =>
  createGeminiAdapter({ ...deps, retry: { sleep: async () => {}, random: () => 0 } }).call(REQ, { creds: { apiKey: "FAKE-KEY" }, step: 0, signal });

await test("isAbortedError: ABORTED provider errors and AbortError, nothing else", () => {
  assert.equal(errors.isAbortedError(errors.abortedError()), true);
  assert.equal(errors.isAbortedError(Object.assign(new Error("x"), { name: "AbortError" })), true);
  assert.equal(errors.isAbortedError(new errors.ProviderError({ kind: "network", code: "DEADLINE_EXCEEDED", message: "slow" })), false);
  assert.equal(errors.isAbortedError(new errors.ProviderError({ kind: "unavailable", message: "503" })), false);
  assert.equal(errors.isAbortedError(new Error("boom")), false);
  assert.equal(errors.isAbortedError("AbortError"), false);
});

await test("Gemini: the caller's signal reaches fetch, and aborting mid-request throws ABORTED", async () => {
  const { fetch, calls } = fakeFetch({ hang: true });
  const ac = new AbortController();
  const pending = geminiCall({ fetch }, ac.signal);
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.signal, ac.signal, "fetch got the caller's signal");
  ac.abort();
  await assert.rejects(pending, (e) => e instanceof errors.ProviderError && e.code === "ABORTED" && errors.isAbortedError(e));
});

await test("Gemini: a signal that already fired sends no request", async () => {
  const { fetch, calls } = fakeFetch();
  const ac = new AbortController();
  ac.abort();
  await assert.rejects(geminiCall({ fetch }, ac.signal), (e) => e.code === "ABORTED");
  assert.equal(calls.length, 0);
});

await test("Gemini: with no signal the request init carries none and the call works as before", async () => {
  const { fetch, calls } = fakeFetch();
  const turn = await geminiCall({ fetch }, undefined);
  assert.deepEqual(turn.text, ["ok"]);
  assert.equal("signal" in calls[0].init, false);
});

await test("Gemini: an ordinary failure while a live signal is attached is not reported as a cancel", async () => {
  const fetch = async () => ({ ok: false, status: 400, text: async () => "bad", json: async () => ({}) });
  const ac = new AbortController();
  await assert.rejects(geminiCall({ fetch }, ac.signal), (e) => !errors.isAbortedError(e) && /Gemini API error: 400/.test(e.message));
});

await test("dispatch.callModel and summarizeText hand the signal to the adapter", async () => {
  const seen = [];
  const adapter = {
    id: "vertex",
    capabilities: {},
    async call(_req, ctx) { seen.push(ctx.signal); return { provider: "vertex", model: "m", text: ["done"], thinking: [], toolCalls: [], finish: "stop", usage: null, leakedToolCallSuspected: false, raw: [] }; },
  };
  const ac = new AbortController();
  await dispatch.callModel(REQ, { creds: {}, signal: ac.signal }, { adapters: { vertex: adapter } });
  const text = await dispatch.summarizeText(REF, "sys", "user", "summarize", { creds: {}, signal: ac.signal }, { adapters: { vertex: adapter } });
  assert.equal(text, "done");
  assert.deepEqual(seen, [ac.signal, ac.signal]);
});

/* ─── The turn's one signal ─── */

await test("turn abort: the request's abort fires the turn signal", () => {
  const req = new AbortController();
  const t = createTurnAbort(req.signal);
  assert.equal(t.signal.aborted, false);
  req.abort();
  assert.equal(t.signal.aborted, true);
});

await test("turn abort: cancel() (the response stream going away) fires it with the request still open", () => {
  const req = new AbortController();
  const t = createTurnAbort(req.signal);
  t.cancel();
  assert.equal(t.signal.aborted, true);
  assert.equal(req.signal.aborted, false, "the request's own signal is not touched");
  t.cancel();
  req.abort();
});

await test("turn abort: a request that already aborted gives an already-aborted signal; no abort leaves it open", () => {
  const gone = new AbortController();
  gone.abort();
  assert.equal(createTurnAbort(gone.signal).signal.aborted, true);
  assert.equal(createTurnAbort(new AbortController().signal).signal.aborted, false);
});

await test("turn abort: a cancelled turn's signal stops a Gemini call in flight", async () => {
  const { fetch } = fakeFetch({ hang: true });
  const t = createTurnAbort(new AbortController().signal);
  const pending = geminiCall({ fetch }, t.signal);
  await new Promise((r) => setTimeout(r, 5));
  t.cancel();
  await assert.rejects(pending, (e) => errors.isAbortedError(e));
});

/* ─── The chat route: every call site passes a signal; an abort ends quietly ─── */

const routeSource = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "app/api/chat/route.ts"), "utf8");

/** The text of each call to `name(`, from the name through its matching close paren. */
function callsOf(source, name) {
  const out = [];
  let from = 0;
  for (;;) {
    const at = source.indexOf(`${name}(`, from);
    if (at < 0) break;
    from = at + name.length;
    const before = source.slice(Math.max(0, at - 24), at);
    if (/function\s+$/.test(before) || /import\s*\{[^}]*$/.test(before)) continue; // a declaration
    let depth = 0;
    let end = at + name.length;
    for (; end < source.length; end++) {
      if (source[end] === "(") depth++;
      else if (source[end] === ")" && --depth === 0) break;
    }
    out.push(source.slice(at, end + 1));
  }
  return out;
}

await test("route: every callModel, summarizeText and summarizeViaModel call passes a signal", () => {
  for (const name of ["callModel", "summarizeText", "summarizeViaModel"]) {
    const calls = callsOf(routeSource, name);
    assert.ok(calls.length > 0, `${name}: no calls found`);
    for (const call of calls) {
      assert.match(call, /signal|ctx\.signal|turnSignal|args\.signal/, `${name} call without a signal:\n${call.slice(0, 200)}`);
    }
  }
  assert.equal(callsOf(routeSource, "summarizeViaModel").length, 3, "/compress, /plan and auto-compaction");
  assert.match(routeSource, /signal: turnSignal \},\n\s*modelDispatchDeps\(\),\n\s*\);/, "the main turn's model call");
  assert.match(routeSource, /signal: args\.signal \},\n\s*modelDispatchDeps\(\)/, "the subagent's model call");
  assert.match(routeSource, /signal: turnSignal,\n\s*sendEvent,\n\s*controller,/, "slash commands get the turn's signal");
});

await test("route: the stream's cancel() and the request's abort both feed the turn signal", () => {
  assert.match(routeSource, /const turnAbort = createTurnAbort\(request\.signal\);\n\s*const turnSignal = turnAbort\.signal;/);
  assert.match(routeSource, /new ReadableStream\(\{\n\s*cancel\(\) \{\n\s*turnAbort\.cancel\(\);/);
  assert.doesNotMatch(routeSource.replace(/createTurnAbort\(request\.signal\)/, ""), /request\.signal/, "every other use goes through turnSignal");
});

await test("route: an aborted turn closes without an error event or a failure row", () => {
  const catchAt = routeSource.indexOf("} catch (error) {\n        if (isAbortedError(error)");
  assert.ok(catchAt > 0, "the turn's catch checks for a cancel first");
  const quiet = routeSource.slice(catchAt, routeSource.indexOf("console.error('Chat API error:'", catchAt));
  assert.match(quiet, /return;/);
  assert.match(routeSource.slice(catchAt, catchAt + 120), /turnSignal\.aborted/);
  assert.doesNotMatch(quiet, /sendEvent|safeAudit/);
  // /compress, /plan and auto-compaction do not report a failure for a cancel either.
  for (const marker of ["chat: /compress failed", "chat: /plan failed"]) {
    const at = routeSource.indexOf(marker);
    const head = routeSource.slice(routeSource.lastIndexOf("} catch (err) {", at), at);
    assert.match(head, /isAbortedError\(err\) \|\| ctx\.signal\.aborted/, marker);
  }
  const autoFailed = routeSource.indexOf("chat: auto-compaction failed");
  assert.ok(routeSource.slice(autoFailed - 400, autoFailed).includes("if (isAbortedError(err)) throw err;"), "auto-compaction rethrows a cancel");
  // A cancelled subagent is not audited as a failure.
  assert.match(routeSource, /if \(status !== 'cancelled'\) \{\n\s*void safeAudit\(auditAction/);
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall chat abort tests passed");
