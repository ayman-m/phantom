/**
 * Pure scope-mapping helpers for API-key auth on the agent surface.
 * No I/O — consumed by `middleware.ts`. Kept framework-free + side-effect-free
 * so the logic is trivially auditable (this is security code).
 *
 * Coarse model: `GET` → `agent:read`; mutations + `/api/chat` →
 * `agent:write`; `agent:*` (and the legacy `*`) grant both. Credential-
 * management routes are NEVER reachable by an API key regardless of scope —
 * see `isCredentialRoute` (security invariant; mirrors the MCP api_keys
 * surface which already refuses API-key auth on itself).
 */

export type AgentScope = "agent:read" | "agent:write";

/**
 * Route prefixes that manage credentials (provider secrets, per-instance
 * connector secrets, API keys themselves). API keys are denied here even with
 * `agent:*`; these stay session-only. Keep in sync with the credential
 * guardrail in the root CLAUDE.md.
 */
const CREDENTIAL_PREFIXES = [
  "/api/agent/providers",
  "/api/agent/instances",
  "/api/agent/api-keys",
  // Backup and restore move WHOLE credential sets and must be gated the same
  // way, even though neither path looks credential-shaped.
  //
  // GET /api/agent/backup fetches /api/v1/instances?include_secrets=true
  // server-side and streams every connector secret into the zip in cleartext
  // (see backup/route.ts — the flag is hardcoded there, so a caller never has
  // to ask for it). Any agent:read key could retrieve every stored credential.
  //
  // POST /api/agent/restore does the inverse: it POSTs /api/v1/instances with
  // an attacker-supplied `secrets` map under the MCP_TOKEN bearer — exactly
  // the instances_create-with-secrets operation this guardrail exists to
  // prevent, reached from a path the guardrail did not name.
  "/api/agent/backup",
  "/api/agent/restore",
];

export function isCredentialRoute(pathname: string): boolean {
  return CREDENTIAL_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
}

export function requiredScope(pathname: string, method: string): AgentScope {
  if (pathname === "/api/chat" || pathname.startsWith("/api/chat/")) {
    return "agent:write"; // a chat turn invokes tools + an LLM call
  }
  return method.toUpperCase() === "GET" ? "agent:read" : "agent:write";
}

export function scopeSatisfied(scopes: string[], required: AgentScope): boolean {
  if (scopes.includes("*") || scopes.includes("agent:*")) return true;
  return scopes.includes(required);
}
