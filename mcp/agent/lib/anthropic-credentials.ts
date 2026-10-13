/**
 * Anthropic credentials resolver. Reads the Claude API key from the MCP
 * ProviderStore on demand and falls back to the ANTHROPIC_API_KEY env var.
 *
 * Mirrors lib/vertex-credentials.ts. Same caching + bust pattern.
 *
 * # Resolution order
 *
 *   1. ProviderStore "anthropic" instance -> secrets.api_key
 *      (set via the /providers UI -> ProviderStore PUT path)
 *   2. Env var ANTHROPIC_API_KEY (.env-supplied)
 *
 * The first non-empty value wins. Returns null if none configured.
 *
 * Only `api_key` is ever read from the instance. Any other secret slot
 * an older install may still hold on the instance is ignored: never
 * read, never returned, never echoed.
 *
 * # Caching
 *
 * 30-second in-memory cache amortizes the MCP roundtrip cost. Cache
 * invalidation goes through bustAnthropicCredsCache(), called from
 * /providers PUT after a successful update so operators see their
 * change reflected immediately.
 *
 * # Failure mode
 *
 * If the MCP is unreachable or the anthropic provider instance isn't
 * materialized yet, returns null from the store path and falls back
 * to the env var. That's intentional: first-install flow ships env
 * vars in /opt/phantom/.env (e.g. ANTHROPIC_API_KEY), and the
 * ProviderStore path comes online once the operator configures via UI.
 */

interface CacheEntry {
  apiKey: string | null;
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
): Promise<string | null> {
  try {
    const listResp = await fetch(
      `${base}/api/v1/providers?provider_id=${ANTHROPIC_PROVIDER_ID}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(8000),
      },
    );
    if (!listResp.ok) return null;
    const listData = (await listResp.json().catch(() => ({}))) as {
      instances?: McpProviderInstance[];
    };
    const instance = listData.instances?.[0];
    if (!instance) return null;

    // Fetch with secrets in cleartext via ?include_secrets=true. The
    // redacted-by-default GET returns "***" placeholders; we explicitly
    // opt in because the caller needs the cleartext key.
    const detailResp = await fetch(
      `${base}/api/v1/providers/${encodeURIComponent(instance.id)}?include_secrets=true`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(8000),
      },
    );
    if (!detailResp.ok) return null;
    const detailData = (await detailResp.json().catch(() => ({}))) as {
      instance?: McpProviderInstance;
    };
    const fetched = detailData.instance;
    if (!fetched?.secrets) return null;

    const apiKeyRaw = fetched.secrets.api_key;
    return typeof apiKeyRaw === "string" && apiKeyRaw.length > 0
      ? apiKeyRaw
      : null;
  } catch {
    // Transport failure → return null, caller falls back to env.
    // Don't log here — every chat dispatch would spam the log on a
    // misconfigured stack.
    return null;
  }
}

async function refreshCache(): Promise<CacheEntry> {
  let storeApiKey: string | null = null;

  const r = resolveMcpDirect();
  if (r) {
    storeApiKey = await fetchFromStore(r.base, r.token);
  }

  const envApi = (process.env.ANTHROPIC_API_KEY || "").trim() || null;

  const entry: CacheEntry = {
    apiKey: storeApiKey || envApi,
    expiresAt: Date.now() + CACHE_TTL_MS,
  };
  cache = entry;
  return entry;
}

/**
 * Resolve the Anthropic API key for direct API calls. Returns null if
 * no credentials are configured anywhere.
 *
 * Resolution priority:
 *   1. ProviderStore anthropic instance -> secrets.api_key
 *   2. Env var ANTHROPIC_API_KEY
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
 * Drop the cached credentials. Called from /providers PUT after a
 * successful update so the operator's change is visible to the next
 * chat dispatch immediately, not after the 30-second cache TTL.
 */
export function bustAnthropicCredsCache(): void {
  cache = null;
}
