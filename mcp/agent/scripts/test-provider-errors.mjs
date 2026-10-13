#!/usr/bin/env node
/**
 * Anthropic transport errors, retries and the outbound-URL guard
 * (lib/providers/anthropic/{errors,transport}.ts, lib/providers/url-guard.ts)
 * over a fake network: a spend cap is never retried, 529/5xx/dropped streams
 * are, `retry-after` is honoured, a caller abort or the deadline stops the
 * retries, the idle timer fires, redirects are refused, an unsafe base URL
 * never reaches the network, and no error carries the key or a raw body.
 *
 *   node scripts/test-provider-errors.mjs   (npm run test:provider-errors)
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

const { callAnthropicMessages, MAX_RETRIES, MAX_RETRY_AFTER_MS } = await import("../lib/providers/anthropic/transport.ts");
const { providerErrorFromApi, parseRetryAfter, isSpendLimit } = await import("../lib/providers/anthropic/errors.ts");
const { classifyAnthropicError } = await import("../lib/providers/anthropic/adapter.ts");
const { ProviderError, redactSecrets } = await import("../lib/providers/errors.ts");

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "anthropic-sse");
const sseBytes = (name) => readFileSync(join(fixtureDir, name));

let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 6).join("\n     ")); }
}

const KEY = "sk-ant-test12345678";
const CREDS = { apiKey: KEY };
const BODY = { model: "claude-opus-5-5", max_tokens: 10, stream: true, messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }] };
const publicHost = async () => ["203.0.113.10"];

const ok = (name = "text-only.sse") =>
  new Response(sseBytes(name), { status: 200, headers: { "content-type": "text/event-stream", "request-id": "req_ok01" } });
const apiError = (status, error, headers = {}, extra = {}) =>
  new Response(JSON.stringify({ type: "error", error, request_id: "req_err01", ...extra }), {
    status, headers: { "content-type": "application/json", ...headers },
  });

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
  const run = (creds = CREDS, signal) => callAnthropicMessages(BODY, [], creds, deps, signal);
  return { seen, sleeps, warns, run };
}

async function failure(promise) {
  try { await promise; } catch (e) { return e; }
  assert.fail("expected a rejection");
}

/* ─── Never retried ────────────────────────────────────────── */

await test("a tier spend cap (429, enforced_spend_limit_reached, no retry-after) is not retried", async () => {
  const h = harness([apiError(429, { type: "rate_limit_error", message: "Spend limit reached", details: { error_code: "enforced_spend_limit_reached" } })]);
  const err = await failure(h.run());
  assert.ok(err instanceof ProviderError);
  assert.equal(err.kind, "quota_exhausted");
  assert.equal(err.retryable, false);
  assert.equal(err.status, 429);
  assert.equal(h.seen.length, 1);
  assert.deepEqual(h.sleeps, []);
});

await test("the operator's own usage limit (400 'reached your specified API usage limits') is not retried", async () => {
  const h = harness([apiError(400, { type: "invalid_request_error", message: "You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC." })]);
  const err = await failure(h.run());
  assert.equal(err.kind, "quota_exhausted");
  assert.equal(h.seen.length, 1);
});

await test("billing, auth, permission, not-found and invalid-request errors are not retried and map to their kinds", async () => {
  const table = [
    [402, "billing_error", "quota_exhausted"],
    [401, "authentication_error", "auth"],
    [403, "permission_error", "permission"],
    [404, "not_found_error", "model_not_found"],
    [400, "invalid_request_error", "invalid_request"],
    [413, "request_too_large", "invalid_request"],
  ];
  for (const [status, type, kind] of table) {
    const h = harness([apiError(status, { type, message: "nope" })]);
    const err = await failure(h.run());
    assert.equal(err.kind, kind, `${status} ${type}`);
    assert.equal(err.retryable, false, `${status}`);
    assert.equal(h.seen.length, 1, `${status}`);
  }
});

await test("a context-window overflow (400) is classified context_exceeded and not retried", async () => {
  const h = harness([apiError(400, { type: "invalid_request_error", message: "prompt is too long: 1100000 tokens > 1000000 maximum" })]);
  const err = await failure(h.run());
  assert.equal(err.kind, "context_exceeded");
  assert.equal(h.seen.length, 1);
});

/* ─── Retried ──────────────────────────────────────────────── */

await test("529 is retried with backoff, then the call succeeds", async () => {
  const h = harness([apiError(529, { type: "overloaded_error", message: "Overloaded" }), apiError(529, { type: "overloaded_error", message: "Overloaded" }), ok()]);
  const { message, requestId } = await h.run();
  assert.equal(h.seen.length, 3);
  assert.deepEqual(h.sleeps, [1000, 2000]);
  assert.equal(requestId, "req_ok01");
  assert.equal(message.content[0].text.startsWith("Hello"), true);
});

await test("retries stop after three: four attempts in all, then the overloaded error surfaces", async () => {
  const h = harness([apiError(529, { type: "overloaded_error", message: "Overloaded" })]);
  const err = await failure(h.run());
  assert.equal(MAX_RETRIES, 3);
  assert.equal(h.seen.length, 4);
  assert.deepEqual(h.sleeps, [1000, 2000, 4000]);
  assert.equal(err.kind, "overloaded");
  assert.equal(err.retryable, true);
});

await test("429 honours retry-after: the wait is the longer of the header and the backoff", async () => {
  const h = harness([apiError(429, { type: "rate_limit_error", message: "slow down" }, { "retry-after": "7" }), ok()]);
  await h.run();
  assert.deepEqual(h.sleeps, [7000]);
  assert.equal(h.seen.length, 2);
  const h2 = harness([apiError(429, { type: "rate_limit_error", message: "slow down" }, { "retry-after": "0" }), ok()]);
  await h2.run();
  assert.deepEqual(h2.sleeps, [1000], "a tiny header never shortens the backoff");
});

await test("a retry-after beyond a minute is surfaced, not slept through", async () => {
  const h = harness([apiError(429, { type: "rate_limit_error", message: "slow down" }, { "retry-after": "3600" })]);
  const err = await failure(h.run());
  assert.equal(err.kind, "rate_limit");
  assert.equal(err.retryAfterMs, 3_600_000);
  assert.ok(err.retryAfterMs > MAX_RETRY_AFTER_MS);
  assert.equal(h.seen.length, 1);
  assert.deepEqual(h.sleeps, []);
});

await test("a retry-after that would outlast the deadline is surfaced", async () => {
  let clock = 0;
  const h = harness([apiError(429, { type: "rate_limit_error", message: "x" }, { "retry-after": "30" })], { now: () => clock, deadlineMs: 10_000 });
  const err = await failure(h.run());
  assert.equal(err.kind, "rate_limit");
  assert.equal(h.seen.length, 1);
});

await test("500, 503, 504 and network failures are each retried", async () => {
  const flaky = [
    apiError(500, { type: "api_error", message: "internal" }),
    apiError(503, { type: "api_error", message: "unavailable" }),
    apiError(504, { type: "timeout_error", message: "timeout" }),
    () => { throw new TypeError("fetch failed"); },
  ];
  for (const first of flaky) {
    const one = harness([first, ok()]);
    await one.run();
    assert.equal(one.seen.length, 2);
  }
});

await test("a mid-stream overloaded error and a stream cut before message_stop are retried in full", async () => {
  const a = harness([ok("mid-stream-error.sse"), ok()]);
  const first = await a.run();
  assert.equal(a.seen.length, 2);
  assert.equal(first.message.id, "msg_01TextOnly");
  const b = harness([ok("no-message-stop.sse"), ok()]);
  await b.run();
  assert.equal(b.seen.length, 2);
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

await test("the idle timer ends a silent stream; it is retryable and reports the idle wait", async () => {
  const h = harness([(init) => stalled(init)], { idleTimeoutMs: 25 });
  const err = await failure(h.run());
  assert.equal(err.code, "IDLE_TIMEOUT");
  assert.equal(err.kind, "network");
  assert.equal(h.seen.length, 4, "retried three times");
  assert.match(err.message, /sent nothing for/);
});

await test("any chunk, even a ping, resets the idle timer", async () => {
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
  const { message } = await h.run();
  assert.equal(message.stopReason, "end_turn");
  assert.equal(h.seen.length, 1);
});

await test("the overall deadline is not retried", async () => {
  const h = harness([(init) => stalled(init)], { idleTimeoutMs: 10_000, deadlineMs: 40 });
  const err = await failure(h.run());
  assert.equal(err.code, "DEADLINE_EXCEEDED");
  assert.equal(err.retryable, false);
  assert.equal(h.seen.length, 1);
});

/* ─── Redaction ────────────────────────────────────────────── */

await test("error text is redacted: a key echoed by the server, a bearer token and key= never survive", async () => {
  const h = harness([apiError(401, { type: "authentication_error", message: `invalid key ${KEY}; header Bearer abc.def-ghi; url ?key=AIzaSyA1234567890abcdefghijk&x=1` })]);
  const err = await failure(h.run());
  for (const secret of [KEY, "abc.def-ghi", "AIzaSyA1234567890abcdefghijk"]) assert.doesNotMatch(err.message, new RegExp(secret.replace(/[.]/g, "\\.")));
  assert.equal(redactSecrets(`token sk-ant-api03-abcdefghijklmnop and sk-proj-abcdefghijklmnop12345`), "token sk-ant-*** and sk-***");
});

await test("the key travels only in the Authorization header: not in the body, the URL, the retry log or any error", async () => {
  const h = harness([apiError(529, { type: "overloaded_error", message: "Overloaded" }), apiError(500, { type: "api_error", message: "oops" }), ok()]);
  await h.run();
  for (const { url, init } of h.seen) {
    assert.equal(init.headers.Authorization, `Bearer ${KEY}`);
    assert.doesNotMatch(url, /sk-ant/);
    assert.doesNotMatch(String(init.body), /sk-ant/);
  }
  for (const line of h.warns) assert.doesNotMatch(line, /sk-ant|Bearer/);
  const net = harness([() => { throw new TypeError(`fetch failed for ${KEY}`); }]);
  const err = await failure(net.run());
  assert.doesNotMatch(err.message, /sk-ant-test/);
});

await test("a missing key fails with PROVIDER_NOT_CONFIGURED before any request", async () => {
  const h = harness([ok()]);
  for (const creds of [{}, { apiKey: "   " }]) {
    const err = await failure(h.run(creds));
    assert.equal(err.code, "PROVIDER_NOT_CONFIGURED");
  }
  assert.equal(h.seen.length, 0);
});

/* ─── Outbound URL guard, on every call ────────────────────── */

const UNSAFE = [
  ["http scheme", "http://api.example.com"],
  ["loopback name", "https://localhost"],
  ["loopback address", "https://127.0.0.1"],
  ["IPv6 loopback", "https://[::1]"],
  ["IPv4-mapped loopback", "https://[::ffff:127.0.0.1]"],
  ["link-local metadata", "https://169.254.169.254"],
  ["EC2 IPv6 metadata", "https://[fd00:ec2::254]"],
  ["compose service", "https://phantom-agent"],
  ["compose service with dot", "https://xlog.internal"],
  ["caldera", "https://caldera"],
  ["single-label host", "https://gateway"],
  [".local suffix", "https://printer.local"],
  ["credentials in URL", `https://user:${KEY}@api.example.com`],
  ["query string", "https://api.example.com/?key=1"],
  ["fragment", "https://api.example.com/#x"],
  ["not a URL", "api.example.com"],
];
for (const [label, baseUrl] of UNSAFE) {
  await test(`guard: ${label} is refused before any request`, async () => {
    const h = harness([ok()]);
    const err = await failure(h.run({ apiKey: KEY, baseUrl }));
    assert.equal(err.code, "BASE_URL_REJECTED", baseUrl);
    assert.equal(h.seen.length, 0);
    assert.doesNotMatch(err.message, /sk-ant-test/);
  });
}

await test("guard: a name that resolves to a loopback or link-local address is refused at call time", async () => {
  for (const address of ["127.0.0.1", "169.254.169.254", "::1"]) {
    const h = harness([ok()], { resolveHost: async () => ["203.0.113.5", address] });
    const err = await failure(h.run({ apiKey: KEY, baseUrl: "https://rebind.example.com" }));
    assert.equal(err.code, "BASE_URL_REJECTED", address);
    assert.equal(h.seen.length, 0);
  }
});

await test("guard: the MCP host handed in by the server is refused", async () => {
  const h = harness([ok()], { blockedHosts: ["mcp.corp.example"] });
  const err = await failure(h.run({ apiKey: KEY, baseUrl: "https://mcp.corp.example" }));
  assert.equal(err.code, "BASE_URL_REJECTED");
  assert.equal(h.seen.length, 0);
});

await test("guard: a public host and a private-range corporate gateway are allowed; the path is kept", async () => {
  const h = harness([ok()]);
  await h.run({ apiKey: KEY, baseUrl: "https://llm.gateway.example.com/anthropic/" });
  assert.equal(h.seen[0].url, "https://llm.gateway.example.com/anthropic/v1/messages");
  const priv = harness([ok()], { resolveHost: async () => ["10.20.30.40"] });
  await priv.run({ apiKey: KEY, baseUrl: "https://10.20.30.40" });
  assert.equal(priv.seen.length, 1);
});

await test("guard: a redirect is never followed and carries no key onward", async () => {
  const redirect = new Response(null, { status: 302, headers: { location: "https://evil.example.net/steal" } });
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

await test("providerErrorFromApi: the request id comes from the header, else the body; unknown shapes still produce an error", () => {
  const a = providerErrorFromApi({ status: 500, body: { error: { type: "api_error", message: "x" }, request_id: "req_body" }, requestId: "req_header" });
  assert.equal(a.requestId, "req_header");
  assert.match(a.message, /\[request req_header\]/);
  const b = providerErrorFromApi({ status: 500, body: { error: { type: "api_error", message: "x" }, request_id: "req_body" } });
  assert.equal(b.requestId, "req_body");
  const c = providerErrorFromApi({ status: 418, body: "teapot" });
  assert.equal(c.kind, "unknown");
  assert.equal(c.retryable, false);
  assert.match(c.message, /no detail was given/);
  const d = providerErrorFromApi({ body: { error: { type: "rate_limit_error", message: "x" } } });
  assert.equal(d.kind, "rate_limit");
  assert.match(d.message, /rate_limit_error/);
});

await test("isSpendLimit covers the cap code, the usage-limit text and billing errors only", () => {
  assert.equal(isSpendLimit(429, "rate_limit_error", "x", "enforced_spend_limit_reached"), true);
  assert.equal(isSpendLimit(400, "invalid_request_error", "You have reached your specified API usage limits.", undefined), true);
  assert.equal(isSpendLimit(402, "billing_error", "x", undefined), true);
  assert.equal(isSpendLimit(429, "rate_limit_error", "Number of requests exceeded", undefined), false);
});

await test("parseRetryAfter: seconds, HTTP dates, and junk", () => {
  assert.equal(parseRetryAfter("12"), 12_000);
  assert.equal(parseRetryAfter("0"), 0);
  assert.equal(parseRetryAfter("1.5"), 1500);
  assert.equal(parseRetryAfter("Wed, 21 Oct 2026 07:28:30 GMT", () => Date.parse("Wed, 21 Oct 2026 07:28:00 GMT")), 30_000);
  assert.equal(parseRetryAfter("soon"), undefined);
  assert.equal(parseRetryAfter(null), undefined);
});

await test("classifyAnthropicError passes ProviderErrors through and tags socket failures as retryable network errors", () => {
  const p = new ProviderError({ kind: "auth", message: "x" });
  assert.equal(classifyAnthropicError(p), p);
  const n = classifyAnthropicError(new Error(`ECONNRESET talking to ${KEY}`));
  assert.equal(n.kind, "network");
  assert.equal(n.retryable, true);
  assert.doesNotMatch(n.message, /sk-ant-test/);
  assert.equal(classifyAnthropicError("weird").kind, "unknown");
});

if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall provider error tests passed");
