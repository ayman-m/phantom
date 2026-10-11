/**
 * Anthropic credentials resolver — reads API key + Claude Code CLI
 * token from the MCP ProviderStore on demand, falls back to env vars.
 *
 * Mirrors lib/vertex-credentials.ts. Same caching + bust pattern.
 *
 * # Resolution order
 *
 *   1. ProviderStore "anthropic" instance → secrets.api_key
 *      (set via the /providers UI → ProviderStore PUT path)
 *   2. Env var ANTHROPIC_API_KEY (.env-supplied)
 *   3. Env var CLAUDE_CODE_OAUTH_TOKEN (Claude Code Max subscription
 *      uses an OAuth token instead of an API key; Claude Code CLI
 *      accepts either)
 *
 * The first non-empty value wins. Returns null if none configured.
 *
 * # Two separate fields
 *
 * The /providers page schema has TWO Anthropic key fields:
 *   - anthropicApiKey  — used for direct Anthropic API calls (chat-route)
 *   - anthropicCliKey  — used for the Claude Code CLI shell-out
 *
 * Operators may want different credentials for the two paths (e.g.
 * Max subscription token for CLI, API key for the chat-route loop).
 * resolveAnthropicCliKey() prefers anthropicCliKey if set, else falls
 * through to anthropicApiKey, else env. resolveAnthropicApiKey()
 * does the reverse — both eventually pick a non-empty value if any
 * exists, but the preferred field for each call site wins.
 *
 * # Caching
 *
 * 30-second in-memory cache amortizes the MCP roundtrip cost across
 * the many resolveAnthropicCliKey() calls per chat turn (though for
 * the CLI path that's at most one per turn). Cache invalidation goes
 * through bustAnthropicCredsCache(), called from /providers PUT
 * after a successful update so operators see their change reflected
 * immediately.
 *
 * # Failure mode
 *
 * If the MCP is unreachable or the anthropic provider instance isn't
 * materialized yet, returns null from the store path and falls back
 * to env vars. That's intentional — first-install flow ships env
 * vars in /opt/phantom/.env (e.g. ANTHROPIC_API_KEY), and the
 * ProviderStore path comes online once the operator configures via UI.
 */

interface CacheEntry {
  apiKey: string | null;
  cliKey: string | null;
  expiresAt: number;
}

const CACHE_TTL_MS = 30_000;
const ANTHROPIC_PROVIDER_ID = "anthropic";

let cache: CacheEntry | null = null;

function deriveBaseUrl(mcpUrl: string): string | null {
  try {
    const u = new URL(mcpUrl);
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

function resolveMcpDirect(): { base: string; token: string } | null {
  // Mirror vertex-credentials.ts — read MCP coordinates directly from
  // env to avoid the circular import (getEffectiveRuntimeConfig calls
  // this module to populate Anthropic fields, so we can't call
  // getEffectiveRuntimeConfig back).
  const token = (process.env.MCP_TOKEN || "").trim();
  if (!token) return null;
  const url = (
    process.env.MCP_URL || "http://localhost:8080/api/v1/stream/mcp"
  ).trim();
  const base = deriveBaseUrl(url);
  if (!base) return null;
  return { base, token };
}

interface McpProviderInstance {
  id: string;
  provider_id: string;
  name: string;
  config: Record<string, unknown>;
  secrets: Record<string, unknown>;
}

async function fetchFromStore(
  base: string,
  token: string,
): Promise<{ apiKey: string | null; cliKey: string | null }> {
  const empty = { apiKey: null, cliKey: null };

  try {
    const listResp = await fetch(
      `${base}/api/v1/providers?provider_id=${ANTHROPIC_PROVIDER_ID}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(8000),
      },
    );
    if (!listResp.ok) return empty;
    const listData = (await listResp.json().catch(() => ({}))) as {
      instances?: McpProviderInstance[];
    };
    const instance = listData.instances?.[0];
    if (!instance) return empty;

    // Fetch with secrets in cleartext via ?include_secrets=true. The
    // redacted-by-default GET returns "***" placeholders; we explicitly
    // opt in because we're populating credentials for child-process use.
    const detailResp = await fetch(
      `${base}/api/v1/providers/${encodeURIComponent(instance.id)}?include_secrets=true`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(8000),
      },
    );
    if (!detailResp.ok) return empty;
    const detailData = (await detailResp.json().catch(() => ({}))) as {
      instance?: McpProviderInstance;
    };
    const fetched = detailData.instance;
    if (!fetched?.secrets) return empty;

    const apiKeyRaw = fetched.secrets.api_key;
    const cliKeyRaw = fetched.secrets.cli_key;
    return {
      apiKey: typeof apiKeyRaw === "string" && apiKeyRaw.length > 0 ? apiKeyRaw : null,
      cliKey: typeof cliKeyRaw === "string" && cliKeyRaw.length > 0 ? cliKeyRaw : null,
    };
  } catch {
    // Transport failure → return empty, caller falls back to env.
    // Don't log here — every chat dispatch would spam the log on a
    // misconfigured stack.
    return empty;
  }
}

async function refreshCache(): Promise<CacheEntry> {
  let storeApiKey: string | null = null;
  let storeCliKey: string | null = null;

  const r = resolveMcpDirect();
  if (r) {
    const fetched = await fetchFromStore(r.base, r.token);
    storeApiKey = fetched.apiKey;
    storeCliKey = fetched.cliKey;
  }

  const envApi = (process.env.ANTHROPIC_API_KEY || "").trim() || null;
  const envOauth = (process.env.CLAUDE_CODE_OAUTH_TOKEN || "").trim() || null;

  const apiKey = storeApiKey || envApi || envOauth;
  const cliKey = storeCliKey || envOauth || envApi;

  const entry: CacheEntry = {
    apiKey,
    cliKey,
    expiresAt: Date.now() + CACHE_TTL_MS,
  };
  cache = entry;
  return entry;
}

/**
 * Resolve the Anthropic API key for direct API calls (chat-route's
 * future callAnthropic path). Returns null if no credentials are
 * configured anywhere.
 *
 * Resolution priority:
 *   1. ProviderStore anthropic instance → secrets.api_key
 *   2. Env var ANTHROPIC_API_KEY
 *   3. Env var CLAUDE_CODE_OAUTH_TOKEN (fallback — Claude Code OAuth
 *      tokens authenticate against the same Anthropic API surface)
 */
export async function resolveAnthropicApiKey(): Promise<string | null> {
  const now = Date.now();
  if (cache && cache.expiresAt > now) {
    return cache.apiKey;
  }
  const entry = await refreshCache();
  return entry.apiKey;
}

/**
 * Resolve the credential for Claude Code CLI shell-out. Returns null
 * if no credentials are configured anywhere.
 *
 * Resolution priority:
 *   1. ProviderStore anthropic instance → secrets.cli_key
 *      (operator-set Max OAuth token, preferred for CLI use)
 *   2. Env var CLAUDE_CODE_OAUTH_TOKEN
 *   3. Env var ANTHROPIC_API_KEY (fallback — Claude Code CLI accepts
 *      either an OAuth token or an API key)
 *
 * The CLI accepts both an API key (ANTHROPIC_API_KEY env) and a Max
 * subscription OAuth token (CLAUDE_CODE_OAUTH_TOKEN env). Either
 * works; operator picks based on billing model.
 */
export async function resolveAnthropicCliKey(): Promise<string | null> {
  const now = Date.now();
  if (cache && cache.expiresAt > now) {
    return cache.cliKey;
  }
  const entry = await refreshCache();
  return entry.cliKey;
}

/**
 * Drop the cached credentials. Called from /providers PUT after a
 * successful update so the operator's change is visible to the next
 * chat / CLI dispatch immediately, not after the 30-second cache TTL.
 */
export function bustAnthropicCredsCache(): void {
  cache = null;
}
