/**
 * xlog URL resolver — reads `instance.config.baseUrl` from the active
 * xlog instance in the MCP's InstanceStore. Single source of truth
 * for the agent's xlog reads (currently `/api/agent/health` only;
 * chat tool calls go directly through the MCP, which has its own
 * lifespan-context resolver against the same InstanceStore).
 *
 * The agent does not read XLOG_URL from `process.env` (an
 * entrypoint probe-then-flip would silently mask TLS rollouts and
 * config drift, contradicting the "no hidden workarounds"
 * principle); this module does a live InstanceStore
 * lookup so `/connectors` edits propagate without restart.
 *
 * No cache: the resolver is called from
 * `getEffectiveRuntimeConfig().XLOG_URL`, used today only by
 * `/api/agent/health`. Health is polled ~every 30s by the UI; a
 * localhost roundtrip per call costs a few ms. Adding cache would
 * either delay `/connectors` edits taking effect (annoying UX) or
 * require cache-bust plumbing on every PATCH (extra surface). Skip
 * it; revisit if a hot-path caller emerges.
 *
 * Returns null when no xlog instance is configured yet (pre-setup
 * window) or MCP is unreachable. Caller falls back to env.
 */

const CONNECTOR_ID = "xlog";

interface McpInstance {
  id: string;
  connector_id: string;
  name: string;
  config: Record<string, unknown>;
}

function deriveBaseUrl(mcpUrl: string): string | null {
  try {
    const u = new URL(mcpUrl);
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

export async function resolveXlogUrlFromStore(): Promise<string | null> {
  // Read MCP_URL + MCP_TOKEN directly from process.env — both are
  // bundle-internal (env-first by design). Avoids a circular import
  // through getEffectiveRuntimeConfig (which is the function calling
  // THIS resolver). Same pattern lib/vertex-credentials.ts uses.
  const token = (process.env.MCP_TOKEN || "").trim();
  if (!token) return null;
  const mcpUrl = (
    process.env.MCP_URL || "http://localhost:8080/api/v1/stream/mcp"
  ).trim();
  const base = deriveBaseUrl(mcpUrl);
  if (!base) return null;

  try {
    const resp = await fetch(
      `${base}/api/v1/instances?connector_id=${CONNECTOR_ID}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(8000),
      },
    );
    if (!resp.ok) return null;
    const data = (await resp.json().catch(() => ({}))) as {
      instances?: McpInstance[];
    };
    const instance = data.instances?.[0];
    if (!instance) return null;
    const cfg = instance.config || {};
    // Match the resolution priority used by the MCP-side lifespan
    // resolver in service/phantom_mcp/server.py — baseUrl first, then
    // legacy auto-migrated keys.
    const candidate = cfg.baseUrl || cfg.xlog_url || cfg.url;
    if (typeof candidate !== "string" || !candidate.trim()) return null;
    return candidate.trim().replace(/\/$/, "");
  } catch {
    // Transport failure → null, caller falls back. Don't log here;
    // every health probe would spam the log on a misconfigured stack.
    return null;
  }
}
