#!/usr/bin/env node
/**
 * Behaviour test for the session-lifetime plumbing on the Next.js side:
 *
 *   - bearerRefusal: /api/auth/session-lifetime refuses any Authorization
 *     bearer (API key or MCP_TOKEN) with 403 before the cookie is read
 *   - the route and /api/auth/change-password draw on ONE failure budget
 *     (changePasswordLimiter, same ip:/sid: keys)
 *   - cookieMaxAgeSeconds: the login cookie's Max-Age is derived from the
 *     expiry the MCP returned (no TTL constant), never below 1
 *   - classifyPasswordGatedFailure: only the MCP's tagged 401/403 are "bad
 *     session"/"wrong password"; a bare 403/503 from the bearer gate or any
 *     5xx is a service fault that must not count against the lockout
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the modules).
 *
 *   node scripts/test-auth-session-lifetime.mjs   (npm run test:auth-session-lifetime)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { bearerRefusal, cookieMaxAgeSeconds, classifyPasswordGatedFailure } =
  await import("../lib/auth-route-helpers.ts");
const { changePasswordLimiter, loginLimiter, acquireAll, refundAll, clearAll, checkAll } =
  await import("../lib/auth-rate-limit.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

// ── bearer refusal ──────────────────────────────────────────────────
test("no Authorization header is allowed through (cookie path)", () => {
  assert.equal(bearerRefusal(null), null);
  assert.equal(bearerRefusal(undefined), null);
  assert.equal(bearerRefusal(""), null);
});

test("an API key bearer is refused with 403 api_key_credential_route_forbidden", () => {
  const r = bearerRefusal("Bearer phantom_ak_abcd1234_deadbeef");
  assert.equal(r.status, 403);
  assert.equal(r.body.code, "api_key_credential_route_forbidden");
});

test("the internal token bearer is refused with 403 too", () => {
  const r = bearerRefusal("Bearer 0123456789abcdef");
  assert.equal(r.status, 403);
  assert.equal(r.body.code, "internal_token_credential_route_forbidden");
});

test("the bearer scheme match is case-insensitive", () => {
  assert.equal(bearerRefusal("bearer PHANTOM_AK_x_y").status, 403);
  assert.equal(bearerRefusal("BEARER x").status, 403);
});

test("the refusal never echoes the credential", () => {
  const r = bearerRefusal("Bearer phantom_ak_SECRETSECRET_value");
  assert.doesNotMatch(JSON.stringify(r), /SECRETSECRET/);
});

test("the route applies the refusal before reading the cookie", () => {
  const src = readFileSync(new URL("../app/api/auth/session-lifetime/route.ts", import.meta.url), "utf8");
  const get = src.slice(src.indexOf("export async function GET"), src.indexOf("async function handleSet"));
  const set = src.slice(src.indexOf("async function handleSet"));
  for (const body of [get, set]) {
    assert.ok(body.indexOf("refuseBearer(request)") !== -1, "refuseBearer is called");
    assert.ok(body.indexOf("refuseBearer(request)") < body.indexOf("cookies.get"), "before the cookie is read");
  }
});

// ── shared limiter ──────────────────────────────────────────────────
test("session-lifetime and change-password use the same limiter", () => {
  for (const f of ["session-lifetime", "change-password"]) {
    const src = readFileSync(new URL(`../app/api/auth/${f}/route.ts`, import.meta.url), "utf8");
    assert.match(src, /changePasswordLimiter/, f);
    assert.doesNotMatch(src, /loginLimiter/, f);
  }
});

test("wrong passwords through either form draw on one budget of five", () => {
  const keys = ["ip:10.9.9.9", "sid:aaaa"];
  clearAll(changePasswordLimiter, keys);
  // 3 via change-password + 2 via session-lifetime, each counted on acquire
  // and kept (the password was wrong).
  for (let i = 0; i < 5; i += 1) {
    assert.equal(acquireAll(changePasswordLimiter, keys).allowed, true, `attempt ${i + 1}`);
  }
  assert.equal(acquireAll(changePasswordLimiter, keys).allowed, false, "sixth is locked");
  assert.equal(checkAll(changePasswordLimiter, keys).allowed, false);
  // Sign-in has its own budget and is unaffected.
  assert.equal(checkAll(loginLimiter, keys).allowed, true);
  clearAll(changePasswordLimiter, keys);
});

test("an attempt that proved nothing is refunded and a success clears the counter", () => {
  const keys = ["ip:10.9.9.8", "sid:bbbb"];
  clearAll(changePasswordLimiter, keys);
  for (let i = 0; i < 4; i += 1) acquireAll(changePasswordLimiter, keys);
  acquireAll(changePasswordLimiter, keys);
  refundAll(changePasswordLimiter, keys); // outage: gives the fifth back
  assert.equal(checkAll(changePasswordLimiter, keys).allowed, true);
  clearAll(changePasswordLimiter, keys);
  for (let i = 0; i < 5; i += 1) assert.equal(acquireAll(changePasswordLimiter, keys).allowed, true);
  clearAll(changePasswordLimiter, keys);
});

// ── login cookie Max-Age ────────────────────────────────────────────
test("Max-Age is the time left until the MCP's expires_at_ms", () => {
  const now = 1_800_000_000_000;
  assert.equal(cookieMaxAgeSeconds(now + 10 * 3600 * 1000, now), 36000);
  assert.equal(cookieMaxAgeSeconds(now + 2 * 3600 * 1000, now), 7200);
  assert.equal(cookieMaxAgeSeconds(now + 24 * 3600 * 1000 + 999, now), 86400);
});

test("Max-Age is never below 1 (0 would delete the cookie)", () => {
  const now = 1_800_000_000_000;
  assert.equal(cookieMaxAgeSeconds(now, now), 1);
  assert.equal(cookieMaxAgeSeconds(now - 5000, now), 1);
  assert.equal(cookieMaxAgeSeconds(now + 400, now), 1);
});

test("the login route has no TTL constant of its own", () => {
  const login = readFileSync(new URL("../app/api/auth/login/route.ts", import.meta.url), "utf8");
  assert.match(login, /cookieMaxAgeSeconds\(result\.expiresAtMs/);
  assert.doesNotMatch(login, /SESSION_TTL/);
  const defaults = readFileSync(new URL("../lib/auth-defaults.ts", import.meta.url), "utf8");
  assert.doesNotMatch(defaults, /SESSION_TTL|7200/);
});

// ── MCP answer classification ───────────────────────────────────────
const c = classifyPasswordGatedFailure;

test("tagged 401 is an invalid session", () => {
  assert.equal(c(401, { error: "invalid session", code: "invalid_session" }).reason, "invalid_session");
});

test("tagged 403 is a wrong current password", () => {
  const r = c(403, { error: "current_password is incorrect", code: "current_password_incorrect" });
  assert.equal(r.reason, "current_password_incorrect");
});

test("400 is a validation error and keeps the MCP's message", () => {
  const r = c(400, { error: "hours must be between 1 and 24" });
  assert.equal(r.reason, "validation_error");
  assert.equal(r.detail, "hours must be between 1 and 24");
});

test("a bare 403 from the bearer gate is a service fault, not a wrong password", () => {
  const r = c(403, { error: "invalid token" });
  assert.equal(r.reason, "mcp_unreachable");
  assert.doesNotMatch(r.detail, /incorrect|password/i);
});

test("a bare 401 from the bearer gate is a service fault, not an expired session", () => {
  assert.equal(c(401, { error: "missing or malformed Authorization header" }).reason, "mcp_unreachable");
});

test("503 and any 5xx are service faults without password text", () => {
  for (const status of [500, 502, 503, 504]) {
    const r = c(status, { error: "current_password is incorrect" }); // even a misleading body
    assert.equal(r.reason, "mcp_unreachable", String(status));
    assert.doesNotMatch(r.detail, /incorrect|password/i, String(status));
  }
});

test("an unexpected status is a service fault", () => {
  assert.equal(c(404, {}).reason, "mcp_unreachable");
  assert.equal(c(429, {}).reason, "mcp_unreachable");
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
