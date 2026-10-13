#!/usr/bin/env node
/**
 * OpenAI transport errors, retries and the outbound-URL guard
 * (lib/providers/openai/{errors,transport}.ts, lib/providers/streaming-call.ts,
 * lib/providers/url-guard.ts) over a fake network: exhausted credit (also on a
 * 429) is never retried, 429/5xx/dropped streams are, `retry-after` and
 * `retry-after-ms` are honoured, a caller abort or the deadline stops the
 * retries, the idle timer fires, redirects are refused, an unsafe base URL
 * never reaches the network, and no error carries the key or a raw body.
 *
 * The error body shape ({error: {message, type, code}}) is the documented one
 * and is not yet confirmed against live traffic.
 *
 *   node scripts/test-provider-openai-errors.mjs   (npm run test:provider-openai-errors)
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

const { callOpenAiResponses, requestHeaders } = await import("../lib/providers/openai/transport.ts");
const { MAX_RETRIES, MAX_RETRY_AFTER_MS } = await import("../lib/providers/streaming-call.ts");
const { providerErrorFromApi, isQuotaFailure } = await import("../lib/providers/openai/errors.ts");
const { classifyOpenAiError } = await import("../lib/providers/openai/adapter.ts");
const { ProviderError, redactSecrets } = await import("../lib/providers/errors.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "openai-sse");
const sseBytes = (name) => readFileSync(join(fixtureDir, name));

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const KEY = ["sk", "proj", "TESTKEY" + "q".repeat(16)].join("-");
const GOOGLE_KEY = ["AI", "zaSyA1234567890abcdefghijk"].join("");
const CREDS = { apiKey: KEY };
const BODY = { model: "gpt-6-sol", store: false, stream: true, input: [{ type: "message", role: "user", content: "hi" }] };
const publicHost = async () => ["203.0.113.10"];

const ok = (name = "text-only.sse") =>
  new Response(sseBytes(name), { status: 200, headers: { "content-type": "text/event-stream", "x-request-id": "req_ok01" } });
const apiError = (status, error, headers = {}) =>
  new Response(JSON.stringify({ error }), { status, headers: { "content-type": "application/json", "x-request-id": "req_err01", ...headers } });

/** A response whose body never produces a byte and errors when the request is aborted. */
function stalled(init) {
  return new Response(
    new ReadableStream({
      start(controller) {
        init.signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

function harness(script, over = {}) {
  const seen = [];
  const sleeps = [];
  const warns = [];
  const fetch = async (url, init) => {
    seen.push({ url, init });
    const step = script[Math.min(seen.length - 1, script.length - 1)];
    return typeof step === "function" ? step(init, seen.length) : step.clone ? step.clone() : step;
  };
  const deps = {
    fetch,
    resolveHost: publicHost,
    retry: { sleep: async (ms) => { sleeps.push(ms); }, random: () => 0, warn: (m) => warns.push(m) },
    ...over,
  };
  const run = (creds = CREDS, signal) => callOpenAiResponses(BODY, creds, deps, signal);
  return { seen, sleeps, warns, run };
}

async function failure(promise) {
  try { await promise; } catch (e) { return e; }
  assert.fail("expected a rejection");
}

/* ─── Never retried ────────────────────────────────────────── */

await test("exhausted credit is never retried, even as a 429 (insufficient_quota as code or as type)", async () => {
  for (const error of [
    { message: "You exceeded your current quota, please check your plan and billing details.", type: "insufficient_quota", code: "insufficient_quota" },
    { message: "You exceeded your current quota.", type: "requests", code: "insufficient_quota" },
    { message: "x", type: "insufficient_quota" },
    { message: "Billing hard limit has been reached", type: "invalid_request_error", code: "billing_hard_limit_reached" },
    { message: "You exceeded your current quota, please check your plan and billing details." },
  ]) {
    const h = harness([apiError(429, error)]);
    const err = await failure(h.run());
    assert.ok(err instanceof ProviderError);
    assert.equal(err.kind, "quota_exhausted", JSON.stringify(error));
    assert.equal(err.retryable, false);
    assert.equal(err.status, 429);
    assert.equal(h.seen.length, 1);
    assert.deepEqual(h.sleeps, []);
  }
});

await test("a project or organization spend limit message (400) is not retried", async () => {
  const h = harness([apiError(400, { message: "The project's monthly spend limit has been reached.", type: "invalid_request_error" })]);
  const err = await failure(h.run());
  assert.equal(err.kind, "quota_exhausted");
  assert.equal(h.seen.length, 1);
});

await test("billing, auth, permission, not-found and invalid-request errors are not retried and map to their kinds", async () => {
  const table = [
    [402, { type: "billing_error", message: "pay up" }, "quota_exhausted"],
    [401, { type: "invalid_request_error", code: "invalid_api_key", message: "Incorrect API key provided" }, "auth"],
    [401, { message: "nope" }, "auth"],
    [403, { type: "permission_error", message: "no access to this model" }, "permission"],
    [404, { type: "invalid_request_error", code: "model_not_found", message: "The model does not exist" }, "model_not_found"],
    [400, { type: "invalid_request_error", message: "Unsupported parameter" }, "invalid_request"],
    [413, { message: "too large" }, "invalid_request"],
    [422, { message: "unprocessable" }, "invalid_request"],
  ];
  for (const [status, error, kind] of table) {
    const h = harness([apiError(status, error)]);
    const err = await failure(h.run());
    assert.equal(err.kind, kind, `${status} ${JSON.stringify(error)}`);
    assert.equal(err.retryable, false, `${status}`);
    assert.equal(h.seen.length, 1, `${status}`);
  }
});

await test("a context-window overflow (400) is classified context_exceeded and not retried", async () => {
  for (const error of [
    { type: "invalid_request_error", code: "context_length_exceeded", message: "Your input exceeds the context window of this model." },
    { type: "invalid_request_error", message: "This model's maximum context length is 1050000 tokens." },
  ]) {
    const h = harness([apiError(400, error)]);
    const err = await failure(h.run());
    assert.equal(err.kind, "context_exceeded");
    assert.equal(h.seen.length, 1);
  }
});

/* ─── Retried ──────────────────────────────────────────────── */

await test("429 rate limit is retried with backoff, then the call succeeds", async () => {
  const limited = () => apiError(429, { type: "requests", code: "rate_limit_exceeded", message: "Rate limit reached for gpt-6-sol" });
  const h = harness([limited(), limited(), ok()]);
  const { response, requestId } = await h.run();
  assert.equal(h.seen.length, 3);
  assert.deepEqual(h.sleeps, [1000, 2000]);
  assert.equal(requestId, "req_ok01");
  assert.equal(response.status, "completed");
});

await test("retries stop after three: four attempts in all, then the rate-limit error surfaces", async () => {
  const h = harness([apiError(429, { type: "requests", code: "rate_limit_exceeded", message: "slow down" })]);
  const err = await failure(h.run());
  assert.equal(MAX_RETRIES, 3);
  assert.equal(h.seen.length, 4);
  assert.deepEqual(h.sleeps, [1000, 2000, 4000]);
  assert.equal(err.kind, "rate_limit");
  assert.equal(err.retryable, true);
});

await test("retry-after is honoured: the wait is the longer of the header and the backoff; retry-after-ms wins over it", async () => {
  const limited = (headers) => apiError(429, { code: "rate_limit_exceeded", message: "slow down" }, headers);
  const h = harness([limited({ "retry-after": "7" }), ok()]);
  await h.run();
  assert.deepEqual(h.sleeps, [7000]);
  const tiny = harness([limited({ "retry-after": "0" }), ok()]);
  await tiny.run();
  assert.deepEqual(tiny.sleeps, [1000], "a tiny header never shortens the backoff");
  const ms = harness([limited({ "retry-after": "30", "retry-after-ms": "2500" }), ok()]);
  await ms.run();
  assert.deepEqual(ms.sleeps, [2500]);
});

await test("a retry-after beyond a minute is surfaced, not slept through", async () => {
  const h = harness([apiError(429, { code: "rate_limit_exceeded", message: "slow down" }, { "retry-after": "3600" })]);
  const err = await failure(h.run());
  assert.equal(err.kind, "rate_limit");
  assert.equal(err.retryAfterMs, 3_600_000);
  assert.ok(err.retryAfterMs > MAX_RETRY_AFTER_MS);
  assert.equal(h.seen.length, 1);
});

await test("408, 409, 500, 502, 503, 504 and network failures are each retried", async () => {
  const flaky = [
    apiError(408, { message: "timeout" }),
    apiError(409, { message: "conflict" }),
    apiError(500, { type: "server_error", message: "internal" }),
    apiError(502, { message: "bad gateway" }),
    apiError(503, { message: "slow down" }),
    apiError(504, { message: "gateway timeout" }),
    () => { throw new TypeError("fetch failed"); },
  ];
  for (const first of flaky) {
    const one = harness([first, ok()]);
    await one.run();
    assert.equal(one.seen.length, 2);
  }
  const overloaded = await failure(harness([apiError(503, { message: "overloaded" })]).run());
  assert.equal(overloaded.kind, "overloaded");
});

await test("a response.failed server_error, a mid-stream rate limit and a stream cut before the end are retried in full", async () => {
  for (const first of ["failed.sse", "mid-stream-error.sse", "no-terminal.sse"]) {
    const h = harness([ok(first), ok()]);
    const { response } = await h.run();
    assert.equal(h.seen.length, 2, first);
    assert.equal(response.id, "resp_fixture_1");
  }
});

await test("a response.failed context overflow is not retried", async () => {
  const h = harness([ok("context-exceeded.sse"), ok()]);
  const err = await failure(h.run());
  assert.equal(err.kind, "context_exceeded");
  assert.equal(h.seen.length, 1);
});

await test("an in-stream insufficient_quota error is not retried", async () => {
  const event = `event: error\ndata: ${JSON.stringify({ type: "error", code: "insufficient_quota", message: "You exceeded your current quota." })}\n\n`;
  const h = harness([new Response(event, { status: 200, headers: { "content-type": "text/event-stream" } }), ok()]);
  const err = await failure(h.run());
  assert.equal(err.kind, "quota_exhausted");
  assert.equal(h.seen.length, 1);
});

await test("a non-JSON error body is never echoed, and a gateway 502 is retried", async () => {
  const html = new Response("<html>internal host db-7.corp.example secret=hunter2</html>", { status: 502, headers: { "content-type": "text/html" } });
  const h = harness([html, ok()]);
  await h.run();
  assert.equal(h.seen.length, 2);
  const e = await failure(harness([new Response("<html>db-7.corp.example secret=hunter2</html>", { status: 400, headers: { "content-type": "text/html" } })]).run());
  assert.doesNotMatch(e.message, /db-7|hunter2|html/);
  assert.equal(e.kind, "invalid_request");
});

/* ─── Abort, idle, deadline ────────────────────────────────── */

await test("a caller abort before the call never reaches the network; one in flight is not retried", async () => {
  const pre = new AbortController();
  pre.abort();
  const h = harness([ok()]);
  const e1 = await failure(h.run(CREDS, pre.signal));
  assert.equal(e1.code, "ABORTED");
  assert.equal(h.seen.length, 0);

  const live = new AbortController();
  const h2 = harness([(init) => { setTimeout(() => live.abort(), 15); return stalled(init); }]);
  const e2 = await failure(h2.run(CREDS, live.signal));
  assert.equal(e2.code, "ABORTED");
  assert.equal(e2.retryable, false);
  assert.equal(h2.seen.length, 1, "no retry after an abort");
});

await test("the idle timer ends a silent stream; it is retryable and names OpenAI", async () => {
  const h = harness([(init) => stalled(init)], { idleTimeoutMs: 25 });
  const err = await failure(h.run());
  assert.equal(err.code, "IDLE_TIMEOUT");
  assert.equal(err.kind, "network");
  assert.equal(h.seen.length, 4, "retried three times");
  assert.match(err.message, /OpenAI stream sent nothing for/);
});

await test("any chunk resets the idle timer", async () => {
  const bytes = sseBytes("text-only.sse");
  const slow = () => new Response(
    new ReadableStream({
      async start(controller) {
        for (let i = 0; i < bytes.length; i += 200) {
          await new Promise((r) => setTimeout(r, 20));
          controller.enqueue(new Uint8Array(bytes.subarray(i, i + 200)));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
  const h = harness([slow], { idleTimeoutMs: 60 });
  const { response } = await h.run();
  assert.equal(response.status, "completed");
  assert.equal(h.seen.length, 1);
});

await test("the overall deadline is not retried", async () => {
  const h = harness([(init) => stalled(init)], { idleTimeoutMs: 10_000, deadlineMs: 40 });
  const err = await failure(h.run());
  assert.equal(err.code, "DEADLINE_EXCEEDED");
  assert.equal(err.retryable, false);
  assert.equal(h.seen.length, 1);
  assert.match(err.message, /OpenAI request did not finish/);
});

/* ─── Redaction and the key ────────────────────────────────── */

await test("error text is redacted: a key echoed by the server, a bearer token and key= never survive", async () => {
  const h = harness([apiError(401, { type: "invalid_request_error", code: "invalid_api_key", message: `Incorrect API key provided: ${KEY}; header Bearer abc.def-ghi; url ?key=${GOOGLE_KEY}&x=1` })]);
  const err = await failure(h.run());
  for (const secret of [KEY, "abc.def-ghi", GOOGLE_KEY]) assert.doesNotMatch(err.message, new RegExp(secret.replace(/[.]/g, "\\.")));
  const proj = ["sk", "proj", "abcdefghijklmnop12345"].join("-");
  const svc = ["sk", "svcacct", "abcdefghijklmnop123"].join("-");
  assert.equal(redactSecrets(`token ${proj} and ${svc}`), "token sk-*** and sk-***");
});

await test("the key travels only in the Authorization header: not in the body, the URL, the retry log or any error", async () => {
  const h = harness([apiError(429, { code: "rate_limit_exceeded", message: "slow" }), apiError(500, { message: "oops" }), ok()]);
  await h.run();
  for (const { url, init } of h.seen) {
    assert.equal(init.headers.Authorization, `Bearer ${KEY}`);
    assert.doesNotMatch(url, /sk-proj/);
    assert.doesNotMatch(String(init.body), /sk-proj/);
  }
  for (const line of h.warns) assert.doesNotMatch(line, /sk-proj|Bearer/);
  const net = harness([() => { throw new TypeError(`fetch failed for ${KEY}`); }]);
  const err = await failure(net.run());
  assert.doesNotMatch(err.message, /sk-proj-TESTKEY/);
});

await test("the request id comes from x-request-id and is part of the error text", async () => {
  const err = await failure(harness([apiError(400, { message: "bad" })]).run());
  assert.equal(err.requestId, "req_err01");
  assert.match(err.message, /\[request req_err01\]/);
});

await test("a missing key fails with PROVIDER_NOT_CONFIGURED before any request", async () => {
  const h = harness([ok()]);
  for (const creds of [{}, { apiKey: "   " }]) {
    const err = await failure(h.run(creds));
    assert.equal(err.code, "PROVIDER_NOT_CONFIGURED");
    assert.match(err.message, /OpenAI/);
  }
  assert.equal(h.seen.length, 0);
});

/* ─── Headers ──────────────────────────────────────────────── */

await test("request headers: bearer, JSON, event stream; organization and project only when they are identifiers", () => {
  assert.deepEqual(requestHeaders({ apiKey: KEY }), { Authorization: `Bearer ${KEY}`, "content-type": "application/json", accept: "text/event-stream" });
  const both = requestHeaders({ apiKey: KEY, organization: " org-AbC_123 ", project: "proj_x.y-z" });
  assert.equal(both["OpenAI-Organization"], "org-AbC_123");
  assert.equal(both["OpenAI-Project"], "proj_x.y-z");
  for (const bad of ["org with space", "org\r\nX: 1", "-lead", "a".repeat(200), "ünï"]) {
    const h = requestHeaders({ apiKey: KEY, organization: bad, project: bad });
    assert.equal("OpenAI-Organization" in h, false, JSON.stringify(bad));
    assert.equal("OpenAI-Project" in h, false, JSON.stringify(bad));
  }
});

/* ─── Outbound URL guard, on every call ────────────────────── */

const UNSAFE = [
  ["http scheme", "http://api.example.com/v1"],
  ["loopback name", "https://localhost/v1"],
  ["loopback address", "https://127.0.0.1/v1"],
  ["IPv6 loopback", "https://[::1]/v1"],
  ["IPv4-mapped loopback", "https://[::ffff:127.0.0.1]/v1"],
  ["link-local metadata", "https://169.254.169.254/v1"],
  ["EC2 IPv6 metadata", "https://[fd00:ec2::254]/v1"],
  ["compose service", "https://phantom-agent/v1"],
  ["compose service with dot", "https://xlog.internal/v1"],
  ["caldera", "https://caldera/v1"],
  ["single-label host", "https://gateway/v1"],
  [".local suffix", "https://printer.local/v1"],
  ["credentials in URL", `https://user:${KEY}@api.example.com/v1`],
  ["query string", "https://api.example.com/v1?key=1"],
  ["fragment", "https://api.example.com/v1#x"],
  ["not a URL", "api.example.com/v1"],
];
for (const [label, baseUrl] of UNSAFE) {
  await test(`guard: ${label} is refused before any request`, async () => {
    const h = harness([ok()]);
    const err = await failure(h.run({ apiKey: KEY, baseUrl }));
    assert.equal(err.code, "BASE_URL_REJECTED", baseUrl);
    assert.equal(h.seen.length, 0);
    assert.doesNotMatch(err.message, /sk-proj-TESTKEY/);
  });
}

await test("guard: a name that resolves to a loopback or link-local address is refused at call time (DNS rebinding)", async () => {
  for (const address of ["127.0.0.1", "169.254.169.254", "::1"]) {
    const h = harness([ok()], { resolveHost: async () => ["203.0.113.5", address] });
    const err = await failure(h.run({ apiKey: KEY, baseUrl: "https://rebind.example.com/v1" }));
    assert.equal(err.code, "BASE_URL_REJECTED", address);
    assert.equal(h.seen.length, 0);
  }
});

await test("guard: the MCP host handed in by the server is refused", async () => {
  const h = harness([ok()], { blockedHosts: ["mcp.corp.example"] });
  const err = await failure(h.run({ apiKey: KEY, baseUrl: "https://mcp.corp.example/v1" }));
  assert.equal(err.code, "BASE_URL_REJECTED");
  assert.equal(h.seen.length, 0);
});

await test("guard: the default base is api.openai.com/v1; a public gateway keeps its path, with no /v1 added", async () => {
  const dflt = harness([ok()]);
  await dflt.run();
  assert.equal(dflt.seen[0].url, "https://api.openai.com/v1/responses");
  const h = harness([ok()]);
  await h.run({ apiKey: KEY, baseUrl: "https://llm.gateway.example.com/openai/" });
  assert.equal(h.seen[0].url, "https://llm.gateway.example.com/openai/responses");
});

await test("guard: a redirect is never followed and carries no key onward", async () => {
  const redirect = new Response(null, { status: 307, headers: { location: "https://evil.example.net/steal" } });
  const h = harness([redirect]);
  const err = await failure(h.run());
  assert.equal(err.code, "BASE_URL_REDIRECT");
  assert.equal(h.seen.length, 1, "no second request");
  assert.equal(h.seen[0].init.redirect, "manual");
  assert.doesNotMatch(err.message, /evil\.example/);
});

await test("a 200 that is not an event stream is an error, not a silent empty turn", async () => {
  const h = harness([new Response("{}", { status: 200, headers: { "content-type": "application/json" } })]);
  const err = await failure(h.run());
  assert.match(err.message, /did not answer with an event stream/);
  assert.equal(h.seen.length, 1);
});

/* ─── Classification units ─────────────────────────────────── */

await test("providerErrorFromApi: wrapped and flat bodies are both read; unknown shapes still produce an error", () => {
  const wrapped = providerErrorFromApi({ status: 429, body: { error: { type: "requests", code: "rate_limit_exceeded", message: "x" } }, requestId: "req_a" });
  assert.equal(wrapped.kind, "rate_limit");
  assert.match(wrapped.message, /HTTP 429, requests/);
  const flat = providerErrorFromApi({ body: { type: "error", code: "server_error", message: "boom" } });
  assert.equal(flat.kind, "unavailable");
  assert.equal(flat.retryable, true);
  assert.match(flat.message, /server_error/);
  const unknown = providerErrorFromApi({ status: 418, body: "teapot" });
  assert.equal(unknown.kind, "unknown");
  assert.equal(unknown.retryable, false);
  assert.match(unknown.message, /no detail was given/);
  const bare = providerErrorFromApi({ body: undefined });
  assert.equal(bare.kind, "unknown");
  assert.match(bare.message, /stream error/);
});

await test("isQuotaFailure covers the quota codes, the credit text and 402 only", () => {
  assert.equal(isQuotaFailure(429, undefined, "insufficient_quota", ""), true);
  assert.equal(isQuotaFailure(429, "insufficient_quota", undefined, ""), true);
  assert.equal(isQuotaFailure(400, undefined, undefined, "You exceeded your current quota"), true);
  assert.equal(isQuotaFailure(402, undefined, undefined, ""), true);
  assert.equal(isQuotaFailure(429, "requests", "rate_limit_exceeded", "Rate limit reached for requests"), false);
  assert.equal(isQuotaFailure(429, "tokens", undefined, "Rate limit reached for gpt-6-sol in organization on tokens per min"), false);
});

await test("classifyOpenAiError passes ProviderErrors through and tags socket failures as retryable network errors", () => {
  const p = new ProviderError({ kind: "auth", message: "x" });
  assert.equal(classifyOpenAiError(p), p);
  const n = classifyOpenAiError(new Error(`ECONNRESET talking to ${KEY}`));
  assert.equal(n.kind, "network");
  assert.equal(n.retryable, true);
  assert.doesNotMatch(n.message, /sk-proj-TESTKEY/);
  assert.equal(classifyOpenAiError("weird").kind, "unknown");
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall OpenAI error tests passed");
