#!/usr/bin/env node
/**
 * Behaviour test for lib/auth-rate-limit.ts, the failure limiter shared by
 * /api/auth/login and /api/auth/change-password.
 *
 * Imports the real TypeScript file through Node's built-in type stripping
 * (Node >= 22.18 / 24; the module is written in erasable syntax for this).
 * On an older Node it reports a skip and exits 0, since the build itself
 * type-checks the module.
 *
 *   node scripts/test-auth-rate-limit.mjs        (npm run test:auth-rate-limit)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const {
  FailureLimiter, loginLimiter, changePasswordLimiter, lockedResponseBody,
  acquireAll, checkAll, clearAll, refundAll, getSourceIp, MAX_ENTRIES, PRUNE_AT,
} = await import("../lib/auth-rate-limit.ts");

const T0 = 1_000_000;
const ip = "10.0.0.7";
let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("four wrong guesses leave the source unlocked", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 4; i++) l.recordFailure(ip, T0 + i);
  assert.deepEqual(l.check(ip, T0 + 10), { allowed: true });
});

test("the fifth locks it, with a retry time of the lockout length", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 5; i++) l.recordFailure(ip, T0);
  const gate = l.check(ip, T0 + 1_000);
  assert.equal(gate.allowed, false);
  assert.equal(gate.retryAfter, 59);
});

test("the lock lifts after the lockout and the counter starts again", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 5; i++) l.recordFailure(ip, T0);
  assert.deepEqual(l.check(ip, T0 + 60_001), { allowed: true });
  l.recordFailure(ip, T0 + 60_002); // new window: one failure, not six
  assert.deepEqual(l.check(ip, T0 + 60_003), { allowed: true });
});

test("failures older than the window do not add up", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 4; i++) l.recordFailure(ip, T0);
  l.recordFailure(ip, T0 + 61_000);
  assert.deepEqual(l.check(ip, T0 + 61_001), { allowed: true });
});

test("a success clears the counter", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 4; i++) l.recordFailure(ip, T0);
  l.clear(ip);
  for (let i = 0; i < 4; i++) l.recordFailure(ip, T0 + 1);
  assert.deepEqual(l.check(ip, T0 + 2), { allowed: true });
});

test("sources are independent", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 5; i++) l.recordFailure("10.0.0.1", T0);
  assert.equal(l.check("10.0.0.1", T0 + 1).allowed, false);
  assert.equal(l.check("10.0.0.2", T0 + 1).allowed, true);
});

test("login and change-password count separately", () => {
  const key = "10.9.9.9";
  for (let i = 0; i < 5; i++) changePasswordLimiter.recordFailure(key);
  assert.equal(changePasswordLimiter.check(key).allowed, false);
  assert.equal(loginLimiter.check(key).allowed, true);
  changePasswordLimiter.clear(key);
});

test("the 429 body names the wait", () => {
  assert.deepEqual(lockedResponseBody(42), {
    error: "Too many failed attempts. Try again in 42s.",
    retryAfter: 42,
  });
});

// ── reserve-then-settle: the rules the routes rely on ──────────────────────────

test("parallel guesses cannot all pass: the attempt is counted before the check", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  // Twenty requests arrive "at once": every one reserves synchronously, before any password check returns.
  const results = Array.from({ length: 20 }, () => acquireAll(l, ["k"], T0));
  assert.equal(results.filter((r) => r.allowed).length, 5);
  assert.equal(results.filter((r) => !r.allowed).length, 15);
});

test("a success clears the reservation", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 4; i++) acquireAll(l, ["k"], T0);
  clearAll(l, ["k"]);
  for (let i = 0; i < 5; i++) assert.equal(acquireAll(l, ["k"], T0).allowed, true);
});

test("a refund gives the attempt back (outage or expired session never locks anyone out)", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 20; i++) { assert.equal(acquireAll(l, ["k"], T0).allowed, true); refundAll(l, ["k"]); }
  assert.equal(l.size, 0);
});

test("a refund after the lock was reached lifts it", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 5; i++) acquireAll(l, ["k"], T0);
  assert.equal(checkAll(l, ["k"], T0 + 1).allowed, false);
  l.refund("k");
  assert.equal(checkAll(l, ["k"], T0 + 1).allowed, true);
});

test("several keys: the request is held by whichever is locked, and a denied request counts nothing", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < 5; i++) acquireAll(l, ["sid:A"], T0);          // this session is locked
  const r = acquireAll(l, ["ip:1.2.3.4", "sid:A"], T0 + 1);
  assert.equal(r.allowed, false);
  assert.equal(checkAll(l, ["ip:1.2.3.4"], T0 + 1).allowed, true);    // the address was not charged
  assert.equal(l.size, 1);
});

test("rotating the address does not escape a session lock", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  let allowed = 0;
  for (let i = 0; i < 50; i++) if (acquireAll(l, ["ip:10.0.0." + i, "sid:STOLEN"], T0).allowed) allowed++;
  assert.equal(allowed, 5);
});

test("the source address is the LAST X-Forwarded-For hop, which the proxy appends", () => {
  const req = (h) => ({ headers: new Headers(h) });
  assert.equal(getSourceIp(req({ "x-forwarded-for": "203.0.113.9" })), "203.0.113.9");
  assert.equal(getSourceIp(req({ "x-forwarded-for": "6.6.6.6, 7.7.7.7, 198.51.100.4" })), "198.51.100.4");
  assert.equal(getSourceIp(req({ "x-real-ip": "192.0.2.1" })), "192.0.2.1");
  assert.equal(getSourceIp(req({})), "unknown");
});

test("memory stays bounded however many distinct keys arrive", () => {
  const l = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < MAX_ENTRIES * 2; i++) l.recordFailure("k" + i, T0);
  assert.ok(l.size <= MAX_ENTRIES, "size " + l.size);
  // Expired entries are swept once the map passes PRUNE_AT.
  const m = new FailureLimiter(60_000, 5, 60_000);
  for (let i = 0; i < PRUNE_AT + 5; i++) m.recordFailure("e" + i, T0);
  m.recordFailure("fresh", T0 + 120_000);
  assert.equal(m.size, 1);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
