/**
 * Pure helpers for the cookie-session auth routes (/api/auth/*).
 *
 * Kept in a leaf module with erasable TypeScript only (no imports, no
 * parameter properties, enums or namespaces) so scripts/test-auth-session-
 * lifetime.mjs can import it directly with Node's type stripping.
 */

/** Map a non-2xx answer from a password-gated MCP route (change_password,
 *  session_lifetime) to a typed failure. The MCP tags the two outcomes the
 *  operator can cause with a `code`; everything else is a service fault.
 *
 *    401 + code "invalid_session"             -> invalid_session
 *    403 + code "current_password_incorrect"  -> current_password_incorrect
 *    400                                       -> validation_error
 *    anything else (a bare 401/403 or a 503 from the MCP bearer gate, any
 *    5xx, an unexpected status)                -> mcp_unreachable
 *
 *  Matching on the code, not the bare status, is what keeps a wiring fault
 *  (bad MCP_TOKEN) from being reported as "wrong password" and counted
 *  against the lockout. The detail never reuses the MCP body for the fault
 *  branch, so no "incorrect password" text can leak into it. */
export function classifyPasswordGatedFailure(
  status: number,
  data: Record<string, unknown>,
):
  | {
      ok: false;
      reason: "invalid_session" | "current_password_incorrect" | "validation_error";
      detail: string;
    }
  | { ok: false; reason: "mcp_unreachable"; detail: string } {
  const code = typeof data.code === "string" ? data.code : "";
  const errMsg =
    typeof data.error === "string" ? data.error : `HTTP ${status}`;
  if (status === 401 && code === "invalid_session") {
    return { ok: false, reason: "invalid_session", detail: errMsg };
  }
  if (status === 403 && code === "current_password_incorrect") {
    return { ok: false, reason: "current_password_incorrect", detail: errMsg };
  }
  if (status === 400) {
    return { ok: false, reason: "validation_error", detail: errMsg };
  }
  return {
    ok: false,
    reason: "mcp_unreachable",
    detail: `MCP returned HTTP ${status}`,
  };
}

/**
 * Cookie Max-Age (seconds) for a freshly minted session: the time left until
 * the server-side expiry the MCP returned. Never below 1, because maxAge 0
 * deletes the cookie. There is no TTL constant: the MCP auth store is the only
 * home of the session lifetime.
 */
export function cookieMaxAgeSeconds(expiresAtMs: number, nowMs: number): number {
  return Math.max(1, Math.floor((expiresAtMs - nowMs) / 1000));
}

/**
 * Routes that change a security setting on the cookie-session surface accept
 * the session cookie only. Any `Authorization: Bearer ...` header (an API key
 * or the internal MCP_TOKEN) is refused with 403 before the cookie is read.
 * Returns the refusal, or null when no bearer was sent.
 */
export function bearerRefusal(
  authorizationHeader: string | null | undefined,
): { status: 403; body: { error: string; code: string } } | null {
  const authz = (authorizationHeader ?? "").toLowerCase();
  if (!authz.startsWith("bearer ")) return null;
  return {
    status: 403,
    body: {
      error: "forbidden",
      code: authz.startsWith("bearer phantom_ak_")
        ? "api_key_credential_route_forbidden"
        : "internal_token_credential_route_forbidden",
    },
  };
}
