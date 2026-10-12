/**
 * POST /api/auth/login
 *
 * Authenticates {username, password} against the MCP-side auth_store
 * and sets a server-issued session cookie on success.
 *
 * # Behaviour
 *
 *  - No setup.json / env fallback. The MCP holds the canonical
 *    PBKDF2 hash; if `auth.v1` is missing, the entrypoint failed to
 *    seed defaults and this route returns 503. There is no "try the
 *    UI_PASSWORD env" path.
 *  - Cookie value is a random 32-byte server-side session token
 *    (not a flat marker value). The token's
 *    SHA-256 hash + metadata live in auth_sessions.db on the MCP
 *    side; that's the source of truth on every subsequent request.
 *  - Cookie attributes: HttpOnly + Secure + SameSite=Strict (CSRF
 *    protection without a separate token system).
 *  - Cookie Max-Age = the time left until the `expires_at_ms` the MCP
 *    returned for this session, i.e. the operator-configured session
 *    lifetime (default 2 hours; see /api/auth/session-lifetime). There is
 *    no TTL constant on this side: the MCP auth store is the only home.
 *    After expiry, re-login. No remember-me option.
 *  - Per-source-IP rate limit: 5 failures / 60s → 60s lockout.
 *    In-memory sliding window; resets on container restart.
 *  - Failed logins emit an audit row via the MCP-side auth_store
 *    (`login_failed` action).
 *
 * # Response shape
 *
 *  success: { ok: true, credentialsChanged: bool, username }
 *           Cookie is set on the response. The UI uses
 *           credentialsChanged to decide whether to redirect to
 *           /profile (false = still using defaults).
 *
 *  invalid: 401 { error: "Invalid credentials" }
 *  locked:  429 { error: "...", retryAfter: <seconds> }
 *  no-mcp:  503 { error: "Authentication service unavailable" }
 */

import { NextRequest, NextResponse } from "next/server";

import { ADMIN_USERNAME, SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { cookieMaxAgeSeconds } from "@/lib/auth-route-helpers";
import { login } from "@/lib/auth-store";
import {
  acquireAll,
  checkAll,
  clearAll,
  getSourceIp,
  loginLimiter,
  lockedResponseBody,
  refundAll,
} from "@/lib/auth-rate-limit";

export const dynamic = "force-dynamic";

// ─── Handler ────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  const keys = [getSourceIp(request)];
  const gate = checkAll(loginLimiter, keys);
  if (!gate.allowed) {
    return NextResponse.json(
      lockedResponseBody(gate.retryAfter),
      {
        status: 429,
        headers: { "Retry-After": String(gate.retryAfter) },
      },
    );
  }

  let body: { username?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const username =
    typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";

  if (!username || !password) {
    return NextResponse.json(
      { error: "Username and password are required" },
      { status: 400 },
    );
  }

  // Auth is single-user. Any username other than the canonical
  // ADMIN_USERNAME returns the same 401 as a wrong password so
  // attackers can't enumerate.
  if (username !== ADMIN_USERNAME) {
    loginLimiter.recordFailure(keys[0]);
    return NextResponse.json(
      { error: "Invalid credentials" },
      { status: 401 },
    );
  }

  // Count this attempt BEFORE the (asynchronous) password check, so parallel
  // guesses cannot all slip through the gate; settle it below.
  const reserved = acquireAll(loginLimiter, keys);
  if (!reserved.allowed) {
    return NextResponse.json(lockedResponseBody(reserved.retryAfter), {
      status: 429,
      headers: { "Retry-After": String(reserved.retryAfter) },
    });
  }

  const userAgent = request.headers.get("user-agent") || undefined;
  const result = await login({ username, password, userAgent });

  if (!result.ok) {
    if (result.reason === "invalid_credentials") {
      // Already counted when reserved.
      return NextResponse.json(
        { error: "Invalid credentials" },
        { status: 401 },
      );
    }
    // mcp_unreachable | transport_error — the MCP is down or
    // misconfigured. NOT counted as a credentials failure (so an
    // outage doesn't lock the operator out): give the reservation back.
    refundAll(loginLimiter, keys);
    return NextResponse.json(
      {
        error: "Authentication service unavailable. Please retry.",
        detail: "detail" in result ? result.detail : undefined,
      },
      { status: 503 },
    );
  }

  // Success — clear any pending failures for this IP, set the cookie.
  clearAll(loginLimiter, keys);
  const response = NextResponse.json({
    ok: true,
    credentialsChanged: result.credentialsChanged,
    username: result.username,
  });
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: result.sessionToken,
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    maxAge: cookieMaxAgeSeconds(result.expiresAtMs, Date.now()),
    path: "/",
  });
  return response;
}
