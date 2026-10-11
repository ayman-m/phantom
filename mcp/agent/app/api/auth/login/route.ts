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
 *  - Cookie Max-Age = 7200 (2 hours). After expiry, re-login. No
 *    remember-me option.
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

import {
  ADMIN_USERNAME,
  SESSION_COOKIE_NAME,
  SESSION_TTL_SECONDS,
} from "@/lib/auth-defaults";
import { login } from "@/lib/auth-store";

export const dynamic = "force-dynamic";

// ─── In-memory per-IP rate limit (sliding window) ─────────────────

const WINDOW_MS = 60_000;
const MAX_FAILURES = 5;
const LOCKOUT_MS = 60_000;

interface RateLimitEntry {
  failureCount: number;
  windowResetAt: number;
  lockedUntilMs: number;
}
const rateLimit = new Map<string, RateLimitEntry>();

function getSourceIp(request: NextRequest): string {
  // x-forwarded-for is set by the tls-proxy sidecar in front of
  // Next.js. Fall back to "unknown" for the dev-loopback case where
  // the header isn't present (tests, local debug).
  const xff = request.headers.get("x-forwarded-for");
  if (xff) {
    return xff.split(",")[0]?.trim() || "unknown";
  }
  return request.headers.get("x-real-ip") || "unknown";
}

function rateCheck(ip: string): { allowed: true } | { allowed: false; retryAfter: number } {
  const now = Date.now();
  const entry = rateLimit.get(ip);
  if (entry && entry.lockedUntilMs > now) {
    return {
      allowed: false,
      retryAfter: Math.ceil((entry.lockedUntilMs - now) / 1000),
    };
  }
  // Clean up expired window so the Map doesn't grow unboundedly.
  if (entry && entry.windowResetAt < now && entry.lockedUntilMs <= now) {
    rateLimit.delete(ip);
  }
  return { allowed: true };
}

function recordFailure(ip: string): void {
  const now = Date.now();
  let entry = rateLimit.get(ip);
  if (!entry || entry.windowResetAt < now) {
    entry = {
      failureCount: 0,
      windowResetAt: now + WINDOW_MS,
      lockedUntilMs: 0,
    };
  }
  entry.failureCount += 1;
  if (entry.failureCount >= MAX_FAILURES) {
    entry.lockedUntilMs = now + LOCKOUT_MS;
  }
  rateLimit.set(ip, entry);
}

function clearFailures(ip: string): void {
  rateLimit.delete(ip);
}

// ─── Handler ────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  const ip = getSourceIp(request);
  const gate = rateCheck(ip);
  if (!gate.allowed) {
    return NextResponse.json(
      {
        error: `Too many failed attempts. Try again in ${gate.retryAfter}s.`,
        retryAfter: gate.retryAfter,
      },
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
    recordFailure(ip);
    return NextResponse.json(
      { error: "Invalid credentials" },
      { status: 401 },
    );
  }

  const userAgent = request.headers.get("user-agent") || undefined;
  const result = await login({ username, password, userAgent });

  if (!result.ok) {
    if (result.reason === "invalid_credentials") {
      recordFailure(ip);
      return NextResponse.json(
        { error: "Invalid credentials" },
        { status: 401 },
      );
    }
    // mcp_unreachable | transport_error — the MCP is down or
    // misconfigured. NOT counted as a credentials failure (so an
    // outage doesn't lock the operator out).
    return NextResponse.json(
      {
        error: "Authentication service unavailable. Please retry.",
        detail: "detail" in result ? result.detail : undefined,
      },
      { status: 503 },
    );
  }

  // Success — clear any pending failures for this IP, set the cookie.
  clearFailures(ip);
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
    maxAge: SESSION_TTL_SECONDS,
    path: "/",
  });
  return response;
}
