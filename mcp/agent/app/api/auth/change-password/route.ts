/**
 * POST /api/auth/change-password
 *
 * Operator-initiated password change from /profile. Requires the
 * session cookie AND the current password (second factor — stops a
 * stolen cookie from locking the operator out).
 *
 * Body: { current_password, new_password, confirm_password }
 *
 * Server-side flow:
 *   1. Read session token from the SESSION_COOKIE_NAME cookie.
 *   2. Validate new == confirm, length ≥ 8, new != current.
 *   3. Call auth-store.changePassword (which hits the MCP). The MCP:
 *        - verifies current_password against the stored hash
 *        - writes the new PBKDF2 hash
 *        - sets credentials_changed=true
 *        - revokes ALL sessions for the user
 *   4. Clear the session cookie locally. The operator must log in
 *      again with the new password.
 *
 * Wrong current-password guesses are limited like login (5 in 60 s lock the
 * key out for 60 s, 429 + Retry-After) with their own counter, keyed on BOTH the
 * source address and the session, so a stolen cookie cannot be used to guess
 * the password through this endpoint, from one address or many. The attempt is
 * counted before the password is checked (parallel guesses cannot all slip
 * through) and given back if it proved nothing: validation errors, an expired
 * session, or an unreachable MCP never count.
 *
 * Response:
 *   ok:     { ok: true }                    + cookie cleared
 *   401:    { error: "Invalid session" }    (token missing/expired)
 *   403:    { error: "current_password incorrect" }
 *   429:    { error: "Too many failed attempts...", retryAfter }
 *   400:    { error: "<validation>" }
 *   503:    { error: "Service unavailable" } (MCP unreachable)
 */

import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { changePassword } from "@/lib/auth-store";
import { createHash } from "node:crypto";

import {
  acquireAll,
  changePasswordLimiter,
  checkAll,
  clearAll,
  getSourceIp,
  lockedResponseBody,
  refundAll,
} from "@/lib/auth-rate-limit";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const cookie = request.cookies.get(SESSION_COOKIE_NAME);
  const token = cookie?.value ?? "";
  if (!token) {
    return NextResponse.json(
      { error: "Not authenticated" },
      { status: 401 },
    );
  }

  const keys = [
    `ip:${getSourceIp(request)}`,
    `sid:${createHash("sha256").update(token).digest("hex")}`,
  ];
  const gate = checkAll(changePasswordLimiter, keys);
  if (!gate.allowed) {
    return NextResponse.json(lockedResponseBody(gate.retryAfter), {
      status: 429,
      headers: { "Retry-After": String(gate.retryAfter) },
    });
  }

  let body: {
    current_password?: unknown;
    new_password?: unknown;
    confirm_password?: unknown;
  };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const currentPassword =
    typeof body.current_password === "string" ? body.current_password : "";
  const newPassword =
    typeof body.new_password === "string" ? body.new_password : "";
  const confirmPassword =
    typeof body.confirm_password === "string" ? body.confirm_password : "";

  if (!currentPassword || !newPassword) {
    return NextResponse.json(
      { error: "current_password and new_password are required" },
      { status: 400 },
    );
  }
  if (newPassword !== confirmPassword) {
    return NextResponse.json(
      { error: "new_password and confirm_password do not match" },
      { status: 400 },
    );
  }
  if (newPassword.length < 8) {
    return NextResponse.json(
      { error: "new_password must be at least 8 characters" },
      { status: 400 },
    );
  }
  if (newPassword === currentPassword) {
    return NextResponse.json(
      { error: "new_password must differ from current_password" },
      { status: 400 },
    );
  }

  // Count the attempt now, before the asynchronous check; settle it below.
  const reserved = acquireAll(changePasswordLimiter, keys);
  if (!reserved.allowed) {
    return NextResponse.json(lockedResponseBody(reserved.retryAfter), {
      status: 429,
      headers: { "Retry-After": String(reserved.retryAfter) },
    });
  }

  const result = await changePassword({
    sessionToken: token,
    currentPassword,
    newPassword,
  });

  if (!result.ok) {
    if (result.reason !== "current_password_incorrect") {
      // Expired session, validation error or outage: proved nothing about the password.
      refundAll(changePasswordLimiter, keys);
    }
    if (result.reason === "invalid_session") {
      return NextResponse.json(
        { error: "Session expired. Please sign in again." },
        { status: 401 },
      );
    }
    if (result.reason === "current_password_incorrect") {
      // Already counted when reserved.
      return NextResponse.json(
        { error: "Current password is incorrect" },
        { status: 403 },
      );
    }
    if (result.reason === "validation_error") {
      return NextResponse.json({ error: result.detail }, { status: 400 });
    }
    // mcp_unreachable
    return NextResponse.json(
      {
        error: "Authentication service unavailable. Please retry.",
        detail: result.detail,
      },
      { status: 503 },
    );
  }

  clearAll(changePasswordLimiter, keys);

  // Success — clear the cookie. The operator's current session has
  // been revoked server-side as part of the change (revoke_all);
  // matching cookie-clear keeps client + server in sync.
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
    expires: new Date(0),
  });
  response.headers.set(
    "Cache-Control",
    "no-store, no-cache, must-revalidate, private",
  );
  return response;
}
