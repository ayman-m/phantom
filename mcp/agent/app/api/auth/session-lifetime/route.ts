/**
 * GET / PUT|POST /api/auth/session-lifetime
 *
 * The operator-configurable UI session lifetime (whole hours, 1..24, default
 * 2), edited from /profile. The value lives in the MCP auth store
 * (`auth_settings` table in auth_sessions.db) and nowhere else: the login
 * route derives the cookie Max-Age from the `expires_at_ms` the MCP returns,
 * so there is no second constant here to drift.
 *
 * This is a SECURITY setting on the cookie-session surface (like the other
 * /api/auth/* routes). It is not an agent tool, not a settings key, and not
 * reachable with a bearer: an `Authorization: Bearer ...` header (API key or
 * MCP_TOKEN) is refused with 403 before the cookie is even read. The
 * middleware matcher does not cover /api/auth/*, so this route enforces both
 * checks itself.
 *
 * GET -> { hours, default_hours }
 *   401 { error } no/expired session cookie
 *   403 { error, code } a bearer header was sent
 *   503 { error } MCP unreachable
 *
 * PUT (POST is an alias) body { current_password, hours }
 *   Needs the session cookie AND the current password, same contract as
 *   change-password: a stolen cookie alone must not be able to stretch every
 *   future session to 24 hours. Applies to sessions minted AFTER the change;
 *   existing sessions (including this one) keep their expiry, so no cookie is
 *   touched here.
 *   -> 200 { ok: true, hours, previous_hours, default_hours }
 *   400 { error }  hours is not a whole number in 1..24, or fields missing
 *   401 { error }  no/expired session
 *   403 { error }  wrong current password (or a bearer header was sent)
 *   429 { error, retryAfter }  too many wrong passwords
 *   503 { error }  MCP unreachable
 *
 * Rate limit: this route checks the current password, so it shares
 * `changePasswordLimiter` (same ip: + sid: keys, same acquire/refund/clear
 * pattern) with /api/auth/change-password. Guesses through either form draw
 * on ONE budget, so a stolen cookie gains nothing by alternating between them.
 */

import { NextRequest, NextResponse } from "next/server";
import { createHash } from "node:crypto";

import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { bearerRefusal } from "@/lib/auth-route-helpers";
import {
  getSessionLifetime,
  setSessionLifetime,
  validateSession,
} from "@/lib/auth-store";
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

const NO_STORE = "no-store, no-cache, must-revalidate, private";

function json(body: Record<string, unknown>, status = 200, headers?: HeadersInit) {
  const response = NextResponse.json(body, { status, headers });
  response.headers.set("Cache-Control", NO_STORE);
  return response;
}

/** Refuse any bearer credential. Browsers never send one to this route. */
function refuseBearer(request: NextRequest): NextResponse | null {
  const refusal = bearerRefusal(request.headers.get("authorization"));
  return refusal ? json(refusal.body, refusal.status) : null;
}

export async function GET(request: NextRequest) {
  const refused = refuseBearer(request);
  if (refused) return refused;

  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value ?? "";
  const session = await validateSession(token);
  if (!session.valid) {
    if (session.reason === "mcp_unreachable") {
      return json(
        { error: "Authentication service unavailable. Please retry." },
        503,
      );
    }
    return json({ error: "Not authenticated" }, 401);
  }

  const result = await getSessionLifetime();
  if (!result.ok) {
    return json(
      {
        error: "Authentication service unavailable. Please retry.",
        detail: result.detail,
      },
      503,
    );
  }
  return json({ hours: result.hours, default_hours: result.defaultHours });
}

async function handleSet(request: NextRequest) {
  const refused = refuseBearer(request);
  if (refused) return refused;

  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value ?? "";
  if (!token) {
    return json({ error: "Not authenticated" }, 401);
  }

  const keys = [
    `ip:${getSourceIp(request)}`,
    `sid:${createHash("sha256").update(token).digest("hex")}`,
  ];
  const gate = checkAll(changePasswordLimiter, keys);
  if (!gate.allowed) {
    return json(lockedResponseBody(gate.retryAfter), 429, {
      "Retry-After": String(gate.retryAfter),
    });
  }

  let body: { current_password?: unknown; hours?: unknown };
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }
  const currentPassword =
    typeof body.current_password === "string" ? body.current_password : "";
  if (!currentPassword) {
    return json({ error: "current_password is required" }, 400);
  }
  // The MCP owns the bounds (1..24) and rejects anything else with a 400;
  // here we only make sure there is a number to send.
  if (typeof body.hours !== "number") {
    return json({ error: "hours (whole number) is required" }, 400);
  }

  // Count the attempt now, before the asynchronous check; settle it below.
  const reserved = acquireAll(changePasswordLimiter, keys);
  if (!reserved.allowed) {
    return json(lockedResponseBody(reserved.retryAfter), 429, {
      "Retry-After": String(reserved.retryAfter),
    });
  }

  const result = await setSessionLifetime({
    sessionToken: token,
    currentPassword,
    hours: body.hours,
  });

  if (!result.ok) {
    if (result.reason !== "current_password_incorrect") {
      // Expired session, validation error or outage: proved nothing about the password.
      refundAll(changePasswordLimiter, keys);
    }
    if (result.reason === "invalid_session") {
      return json({ error: "Session expired. Please sign in again." }, 401);
    }
    if (result.reason === "current_password_incorrect") {
      // Already counted when reserved.
      return json({ error: "Current password is incorrect" }, 403);
    }
    if (result.reason === "validation_error") {
      return json({ error: result.detail }, 400);
    }
    // mcp_unreachable
    return json(
      {
        error: "Authentication service unavailable. Please retry.",
        detail: result.detail,
      },
      503,
    );
  }

  clearAll(changePasswordLimiter, keys);
  return json({
    ok: true,
    hours: result.hours,
    previous_hours: result.previousHours,
    default_hours: result.defaultHours,
  });
}

export { handleSet as PUT, handleSet as POST };
