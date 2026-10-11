/**
 * Phantom TypeScript client for the MCP-side auth_store.
 *
 * The MCP-side `bundles/spark/mcp/src/api/ui_auth.py` is the source of
 * truth for credentials + sessions. The Next.js side (login route,
 * change-password route, AuthGate) talks to it through this module.
 *
 * Why a dedicated client (vs ad-hoc fetch calls):
 *
 *  1. Single place that knows how to attach the MCP_TOKEN bearer
 *     and the Content-Type. Routes don't have to repeat the dance.
 *  2. Strongly typed response shapes so downstream consumers can
 *     trust the discriminated unions (LoginOk vs LoginRejected,
 *     SessionValid vs SessionInvalid).
 *  3. Cache hook for the session validation path. It caches
 *     positive session lookups for 30 seconds (config below) so
 *     AuthGate doesn't hammer the MCP on every render. Negative
 *     lookups are NOT cached — if a session was revoked, the next
 *     check should detect it immediately.
 *  4. Centralized error mapping. A 401 from /login is "wrong
 *     credentials" (operator-visible); a 5xx is "MCP down"
 *     (different UX, retry button vs. message). Routes don't need
 *     to interpret HTTP semantics — they get a typed result.
 *
 * # The session-token contract
 *
 * The raw session token NEVER leaves this module's API surface. It
 * goes from MCP /login response → cookie (Set-Cookie header) → back
 * to MCP on subsequent /session validate calls. The Next.js side
 * never persists the token anywhere except the response cookie.
 *
 * # Cache invalidation
 *
 * `bustSessionCache(token)` is exported so the change-password route
 * can flush the entry after revoking sessions — guarantees the next
 * AuthGate check sees the revocation immediately rather than waiting
 * up to 30 seconds for the cached entry to expire.
 */

import { resolveMcp } from "@/lib/mcp-proxy";

const SESSION_CACHE_TTL_MS = 30_000;

// ─────────────────────────────────────────────────────────────────
// Public types — discriminated unions for clean route consumption
// ─────────────────────────────────────────────────────────────────

export interface LoginOk {
  ok: true;
  sessionToken: string;
  expiresAtMs: number;
  credentialsChanged: boolean;
  username: string;
}

export interface LoginRejected {
  ok: false;
  reason: "invalid_credentials";
}

export interface LoginUnavailable {
  ok: false;
  reason: "mcp_unreachable" | "transport_error";
  detail: string;
}

export type LoginResult = LoginOk | LoginRejected | LoginUnavailable;

export interface SessionValid {
  valid: true;
  username: string;
  expiresAtMs: number;
  credentialsChanged: boolean;
}

export interface SessionInvalid {
  valid: false;
  reason: "missing" | "expired_or_revoked" | "mcp_unreachable";
}

export type SessionResult = SessionValid | SessionInvalid;

// ─────────────────────────────────────────────────────────────────
// API-key validation result (agent-surface bearer auth)
// ─────────────────────────────────────────────────────────────────

export interface ApiKeyValid {
  valid: true;
  scopes: string[];
  keyId: string;
  label: string;
}
export interface ApiKeyInvalid {
  valid: false;
  reason: "missing" | "unknown_or_revoked" | "mcp_unreachable";
}
export type ApiKeyResult = ApiKeyValid | ApiKeyInvalid;

export interface ChangePasswordOk {
  ok: true;
  sessionsRevoked: number;
}

export interface ChangePasswordRejected {
  ok: false;
  reason:
    | "invalid_session"
    | "current_password_incorrect"
    | "validation_error"
    | "mcp_unreachable";
  detail: string;
}

export type ChangePasswordResult = ChangePasswordOk | ChangePasswordRejected;

// ─────────────────────────────────────────────────────────────────
// Session validation cache
// ─────────────────────────────────────────────────────────────────

interface CacheEntry {
  result: SessionValid;
  expiresAt: number;
}
const sessionCache = new Map<string, CacheEntry>();

/** Drop a specific token from the session validation cache. Called
 *  after change-password so AuthGate sees the revocation immediately
 *  instead of waiting for the cache TTL. */
export function bustSessionCache(token: string): void {
  sessionCache.delete(token);
}

/** Drop ALL cached session entries. Called on processes-side state
 *  reset for tests; not used in production paths. */
export function clearSessionCacheForTests(): void {
  sessionCache.clear();
}

// ── API-key validation cache (mirrors the session cache) ──────────
interface ApiKeyCacheEntry {
  result: ApiKeyValid;
  expiresAt: number;
}
const apiKeyCache = new Map<string, ApiKeyCacheEntry>();

/** Drop a specific API key from the validation cache. Called after the
 *  revoke route so revocation surfaces immediately rather than waiting
 *  for the cache TTL. */
export function bustApiKeyCache(token: string): void {
  apiKeyCache.delete(token);
}

// ─────────────────────────────────────────────────────────────────
// Internal — bearer-authenticated POST to MCP
// ─────────────────────────────────────────────────────────────────

async function mcpPost(
  path: string,
  body: Record<string, unknown>,
): Promise<
  | { ok: true; status: number; data: Record<string, unknown> }
  | { ok: false; reason: "mcp_unreachable" | "transport_error"; detail: string }
  | { ok: false; reason: "http_error"; status: number; data: Record<string, unknown> }
> {
  const r = await resolveMcp().catch(() => null);
  if (!r || "status" in r) {
    return {
      ok: false,
      reason: "mcp_unreachable",
      detail: "MCP base unresolved",
    };
  }
  try {
    const resp = await fetch(`${r.base}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${r.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await resp.text();
    let data: Record<string, unknown> = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        // MCP should always return JSON; if it didn't, surface raw.
        data = { error: text };
      }
    }
    if (!resp.ok) {
      return { ok: false, reason: "http_error", status: resp.status, data };
    }
    return { ok: true, status: resp.status, data };
  } catch (err) {
    return {
      ok: false,
      reason: "transport_error",
      detail: err instanceof Error ? err.message : String(err),
    };
  }
}

// ─────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────

/** Authenticate username + password. On success returns a fresh
 *  session token + metadata. On rejection returns `ok: false` with
 *  a discriminator. Caller is responsible for setting the cookie. */
export async function login(args: {
  username: string;
  password: string;
  userAgent?: string;
}): Promise<LoginResult> {
  const resp = await mcpPost("/api/v1/ui/auth/login", {
    username: args.username,
    password: args.password,
    user_agent: args.userAgent ?? null,
  });
  if (!resp.ok) {
    // Exhaustive switch — every `reason` literal handled so the
    // post-block resp narrows correctly to {ok: true, ...}.
    switch (resp.reason) {
      case "mcp_unreachable":
        return { ok: false, reason: "mcp_unreachable", detail: resp.detail };
      case "transport_error":
        return { ok: false, reason: "transport_error", detail: resp.detail };
      case "http_error":
        if (resp.status === 401) {
          return { ok: false, reason: "invalid_credentials" };
        }
        return {
          ok: false,
          reason: "transport_error",
          detail: `MCP returned ${resp.status}: ${JSON.stringify(resp.data).slice(0, 200)}`,
        };
    }
  }
  // ok=true path — resp is narrowed to the success variant
  const sessionToken =
    typeof resp.data.session_token === "string" ? resp.data.session_token : "";
  const expiresAtMs =
    typeof resp.data.expires_at_ms === "number" ? resp.data.expires_at_ms : 0;
  const credentialsChanged = Boolean(resp.data.credentials_changed);
  const username =
    typeof resp.data.username === "string" ? resp.data.username : args.username;
  if (!sessionToken || !expiresAtMs) {
    return {
      ok: false,
      reason: "transport_error",
      detail: "MCP login response missing token/expiry",
    };
  }
  return {
    ok: true,
    sessionToken,
    expiresAtMs,
    credentialsChanged,
    username,
  };
}

/** Validate a session token. Cached for 30s for valid tokens to avoid
 *  hammering the MCP on every AuthGate render. Invalid/expired/revoked
 *  tokens are NEVER cached so revocation takes effect immediately. */
export async function validateSession(
  token: string,
): Promise<SessionResult> {
  if (!token) {
    return { valid: false, reason: "missing" };
  }
  const now = Date.now();
  const cached = sessionCache.get(token);
  if (cached && cached.expiresAt > now) {
    return cached.result;
  }

  const resp = await mcpPost("/api/v1/ui/auth/session", {
    session_token: token,
  });
  if (!resp.ok) {
    // Same exhaustive-switch pattern as login() — collapse every
    // failure mode to "mcp_unreachable" since session validation
    // doesn't have a finer-grained "wrong creds" path.
    switch (resp.reason) {
      case "mcp_unreachable":
      case "transport_error":
      case "http_error":
        return { valid: false, reason: "mcp_unreachable" };
    }
  }

  if (!resp.data.valid) {
    return { valid: false, reason: "expired_or_revoked" };
  }

  const result: SessionValid = {
    valid: true,
    username:
      typeof resp.data.username === "string" ? resp.data.username : "admin",
    expiresAtMs:
      typeof resp.data.expires_at_ms === "number"
        ? resp.data.expires_at_ms
        : 0,
    credentialsChanged: Boolean(resp.data.credentials_changed),
  };
  sessionCache.set(token, {
    result,
    expiresAt: now + SESSION_CACHE_TTL_MS,
  });
  return result;
}

/** Validate a `phantom_ak_*` API key against the MCP api_keys store.
 *  30s positive cache (negative results are NOT cached so revocation
 *  surfaces fast). Mirrors `validateSession`. Consumed by middleware.ts. */
export async function validateApiKey(token: string): Promise<ApiKeyResult> {
  if (!token) return { valid: false, reason: "missing" };
  const now = Date.now();
  const cached = apiKeyCache.get(token);
  if (cached && cached.expiresAt > now) return cached.result;

  const resp = await mcpPost("/api/v1/ui/auth/verify_key", { api_key: token });
  if (!resp.ok) {
    switch (resp.reason) {
      case "mcp_unreachable":
      case "transport_error":
      case "http_error":
        return { valid: false, reason: "mcp_unreachable" };
    }
  }
  if (!resp.data.valid) return { valid: false, reason: "unknown_or_revoked" };

  const result: ApiKeyValid = {
    valid: true,
    scopes: Array.isArray(resp.data.scopes) ? (resp.data.scopes as string[]) : [],
    keyId: typeof resp.data.key_id === "string" ? resp.data.key_id : "",
    label: typeof resp.data.label === "string" ? resp.data.label : "",
  };
  apiKeyCache.set(token, { result, expiresAt: now + SESSION_CACHE_TTL_MS });
  return result;
}

/** Revoke a single session. Idempotent — succeeds even if the token
 *  was already revoked or never existed. The MCP returns 200 always
 *  on logout. */
export async function logout(token: string): Promise<void> {
  if (!token) return;
  bustSessionCache(token);
  await mcpPost("/api/v1/ui/auth/logout", { session_token: token });
}

/** Change the password for the user attached to `token`. Requires
 *  the current password as second factor. On success, ALL sessions
 *  for that user are revoked server-side — the caller MUST clear the
 *  client's cookie and redirect to login. */
export async function changePassword(args: {
  sessionToken: string;
  currentPassword: string;
  newPassword: string;
}): Promise<ChangePasswordResult> {
  const resp = await mcpPost("/api/v1/ui/auth/change_password", {
    session_token: args.sessionToken,
    current_password: args.currentPassword,
    new_password: args.newPassword,
  });
  if (!resp.ok) {
    switch (resp.reason) {
      case "mcp_unreachable":
      case "transport_error":
        return {
          ok: false,
          reason: "mcp_unreachable",
          detail: resp.detail ?? "MCP unreachable",
        };
      case "http_error": {
        const errMsg =
          typeof resp.data.error === "string"
            ? resp.data.error
            : `HTTP ${resp.status}`;
        if (resp.status === 401) {
          return { ok: false, reason: "invalid_session", detail: errMsg };
        }
        if (resp.status === 403) {
          return {
            ok: false,
            reason: "current_password_incorrect",
            detail: errMsg,
          };
        }
        return { ok: false, reason: "validation_error", detail: errMsg };
      }
    }
  }
  // ok=true path — bust the cache for the token we just rotated.
  bustSessionCache(args.sessionToken);
  const sessionsRevoked =
    typeof resp.data.sessions_revoked === "number"
      ? resp.data.sessions_revoked
      : 0;
  return { ok: true, sessionsRevoked };
}
