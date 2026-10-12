/**
 * Vertex credentials resolver — reads service-account JSON from the
 * MCP ProviderStore on demand.
 *
 * Why this module exists: per the canonical setup spec at
 * /help/architecture#setup-wiring, ProviderStore is the master
 * for provider data. /providers PUT writes there directly. Without
 * this resolver, post-install Vertex JSON edits via /providers
 * wouldn't take effect for chat dispatches.
 *
 * Caching: a 30-second in-memory cache amortizes the MCP roundtrip
 * cost across the many getEffectiveRuntimeConfig calls per chat
 * turn. Cache invalidation goes through `bustVertexCredsCache()`,
 * called from /providers PUT after a successful update so operators
 * see their change reflected immediately, not after a 30-second
 * delay.
 *
 * Failure mode: if the MCP is unreachable or the vertex provider
 * isn't materialized yet (nothing saved at /providers), this returns
 * null and the caller falls back to the GOOGLE_APPLICATION_CREDENTIALS
 * env var. That's intentional — chat should keep working in those
 * states even if the SecretStore lookup fails.
 */

// Note: this module deliberately does NOT call resolveMcp() from
// mcp-proxy.ts. resolveMcp uses getEffectiveRuntimeConfig to fetch
// MCP_URL+MCP_TOKEN, and getEffectiveRuntimeConfig calls THIS module
// to populate GOOGLE_APPLICATION_CREDENTIALS — that's a circular
// dependency that hangs the process. We read MCP_URL+MCP_TOKEN
// directly from process.env here. Both are bundle-internal keys
// (env-first by design — see BUNDLE_INTERNAL_KEYS in runtime-config),
// so reading them from env directly is correct.

interface CacheEntry {
  value: string | null;
  expiresAt: number;
}

const CACHE_TTL_MS = 30_000;
const VERTEX_PROVIDER_ID = "vertex";

let cache: CacheEntry | null = null;

function deriveBaseUrl(mcpUrl: string): string | null {
  // Mirror lib/runtime-config::deriveMcpBaseUrl — strip the
  // /api/v1/stream/mcp suffix from MCP_URL to get the base URL we
  // can hit /api/v1/* on.
  try {
    const u = new URL(mcpUrl);
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

function resolveMcpDirect(): { base: string; token: string } | null {
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

async function fetchUncached(
  base: string,
  token: string,
): Promise<string | null> {
  // Step 1: list vertex provider instances. Convention is one
  // primary-vertex per install, but we just take the first.
  const listResp = await fetch(
    `${base}/api/v1/providers?provider_id=${VERTEX_PROVIDER_ID}`,
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

  // Step 2: fetch the instance with secrets in cleartext via
  // ?include_secrets=true. The redacted-by-default GET endpoint
  // returns "***" placeholders; we explicitly opt in to cleartext
  // because we're populating GOOGLE_APPLICATION_CREDENTIALS for
  // chat-handler use.
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
  const sa = fetched?.secrets?.serviceAccountJson;
  if (typeof sa !== "string" || sa.length === 0) return null;
  return sa;
}

/**
 * Resolve the Vertex service-account JSON from the ProviderStore.
 * Returns null if no vertex provider is configured or if MCP is
 * unreachable. Caches the result for 30 seconds.
 *
 * Used by `getEffectiveRuntimeConfig` to populate the
 * `GOOGLE_APPLICATION_CREDENTIALS` field. Chat handler reads that
 * field via `runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS` — so the
 * 16+ existing call sites continue to work unchanged, they just
 * receive ProviderStore-backed data.
 */
export async function resolveVertexCredentialsFromStore(): Promise<
  string | null
> {
  const now = Date.now();
  if (cache && cache.expiresAt > now) {
    return cache.value;
  }

  let value: string | null = null;
  try {
    const r = resolveMcpDirect();
    if (r) {
      value = await fetchUncached(r.base, r.token);
    }
  } catch {
    // Transport failure → null, caller falls back. Don't log here;
    // every chat dispatch would spam the log on a misconfigured stack.
  }

  cache = { value, expiresAt: now + CACHE_TTL_MS };
  return value;
}

/**
 * Drop the cached credentials. Called from /providers PUT after a
 * successful update so the operator's change is visible to the next
 * chat dispatch immediately, not after the 30-second cache TTL.
 */
export function bustVertexCredsCache(): void {
  cache = null;
}
