/**
 * POST /api/auth/logout
 *
 * Revokes the session server-side AND clears the cookie. Idempotent:
 * if no cookie is present (or it's already revoked), the response is
 * still 200 — the operator's intent ("end this session") is satisfied
 * either way.
 *
 * Server-side revocation is the important half: clearing the cookie
 * alone wouldn't stop an attacker who already grabbed it. By calling
 * the MCP's /api/v1/ui/auth/logout, we hash the token and mark its
 * row in auth_sessions.db as revoked. Any subsequent validateSession()
 * call for that token returns invalid.
 */

import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { logout } from "@/lib/auth-store";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const cookie = request.cookies.get(SESSION_COOKIE_NAME);
  const token = cookie?.value ?? "";

  if (token) {
    // Fire-and-forget — if the MCP is unreachable we still clear the
    // cookie locally. Server-side revocation is best-effort; the
    // cookie-clear plus the natural 2h expiry guarantees the session
    // can't live forever.
    try {
      await logout(token);
    } catch {
      // swallow — cookie clear below is what matters most.
    }
  }

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
  response.headers.set("Pragma", "no-cache");
  return response;
}
