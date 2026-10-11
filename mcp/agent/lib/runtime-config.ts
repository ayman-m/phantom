/**
 * Phantom runtime configuration resolution.
 *
 * Reads bundle-internal coordination from container env, operator-set
 * provider credentials from the MCP-side ProviderStore, and xlog URL
 * from the InstanceStore. Returns a single flat `EffectiveRuntimeConfig`
 * the chat handler + agent routes consume.
 *
 * # Design
 *
 *  - There is no setup page and no `setup.json`: no operator-typed
 *    values are layered over env.
 *  - There are no `UI_USER` / `UI_PASSWORD` env vars. Admin auth lives ONLY in
 *    SecretStore via `lib/auth-store.ts` + the baked
 *    `ADMIN_USERNAME` constant in `lib/auth-defaults.ts`. No env
 *    fallback, no setup.json fallback.
 *  - AuthGate does not branch on a "setup needed" state — defaults
 *    are seeded by entrypoint.sh on first boot, login works
 *    immediately.
 *  - GEMINI_MODEL / defaultLogFormat
 *    fall back to env defaults; operator overrides via
 *    /settings/personality flow into settings_store and are read by
 *    the MCP side, not by this module.
 *
 * # Layering
 *
 *   env  →  ProviderStore (Vertex SA JSON)  →  InstanceStore (xlog URL)
 *
 * Provider/instance lookups have 30s caches in their own modules
 * (lib/vertex-credentials.ts, lib/xlog-url.ts); a fresh
 * getEffectiveRuntimeConfig() does at most one round-trip per cache
 * window, not per chat turn.
 */

/* ─── Types ─────────────────────────────────────────────────── */

export type RuntimeConfigValues = {
  MCP_URL?: string;
  MCP_TOKEN?: string;
  GOOGLE_APPLICATION_CREDENTIALS?: string;
  GEMINI_API_KEY?: string;
  GEMINI_MODEL?: string;
  SSL_CERT_PEM?: string;
  SSL_KEY_PEM?: string;
  PHANTOM_TLS_VERIFY?: string;
  // Bundle-derived fields (connector configs) flow through here. Names
  // come from the bundle's connector.yaml configSchemas; we don't
  // enumerate them — consumers just read by key.
  [key: string]: string | undefined;
};

export type EffectiveRuntimeConfig = RuntimeConfigValues & {
  MCP_URL: string;
  XLOG_URL: string;
  MCP_TOOL_CACHE_TTL_MS: string;
};

/* ─── Constants ────────────────────────────────────────────── */

const DEFAULT_MODEL = "gemini-3.1-pro-preview";

/** Bundle-internal coordination keys. Container env wins; never
 *  operator-typed. The embedded MCP reads MCP_TOKEN from the same
 *  process env, so divergence between agent-side and MCP-side would
 *  break every admin /api/v1/* call. We pin both to env. */
const BUNDLE_INTERNAL_KEYS: ReadonlySet<string> = new Set(["MCP_URL", "MCP_TOKEN"]);

/* ─── Internal helpers ─────────────────────────────────────── */

function clean(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function envValue(key: string | number | symbol): string {
  if (typeof key !== "string") return "";
  return clean(process.env[key]);
}

/* ─── Public API ───────────────────────────────────────────── */

/**
 * Resolve the effective runtime config for one chat turn (or one
 * /api/agent/* proxy call). Reads env directly + lazily imports the
 * provider/instance resolvers so this module stays free of MCP
 * client wiring.
 */
export async function getEffectiveRuntimeConfig(): Promise<EffectiveRuntimeConfig> {
  const get = (key: keyof RuntimeConfigValues, fallback = ""): string => {
    if (typeof key === "string" && BUNDLE_INTERNAL_KEYS.has(key)) {
      // Env wins for bundle-internal keys.
      return envValue(key) || fallback;
    }
    return envValue(key) || fallback;
  };

  // Provider credentials live in the MCP-side
  // ProviderStore. The chat handler reads `GOOGLE_APPLICATION_CREDENTIALS`
  // here at ~16 call sites; the resolution path sits underneath
  // them without changing the read signature.
  const { resolveVertexCredentialsFromStore } = await import(
    "@/lib/vertex-credentials"
  );
  const vertexFromStore = await resolveVertexCredentialsFromStore();

  // The xlog URL lives in the MCP-side InstanceStore.
  // The instance is created by the operator at /instances post-login.
  // Pre-instance, falls back to the env default.
  const { resolveXlogUrlFromStore } = await import("@/lib/xlog-url");
  const xlogFromStore = await resolveXlogUrlFromStore();

  return {
    MCP_URL: get("MCP_URL", "http://localhost:8080/api/v1/stream/mcp"),
    MCP_TOKEN: get("MCP_TOKEN"),
    GOOGLE_APPLICATION_CREDENTIALS:
      vertexFromStore || get("GOOGLE_APPLICATION_CREDENTIALS"),
    GEMINI_API_KEY: get("GEMINI_API_KEY"),
    GEMINI_MODEL: get("GEMINI_MODEL", DEFAULT_MODEL),
    SSL_CERT_PEM: get("SSL_CERT_PEM"),
    SSL_KEY_PEM: get("SSL_KEY_PEM"),
    PHANTOM_TLS_VERIFY: get("PHANTOM_TLS_VERIFY"),
    // Default is https. The architectural
    // truth: xlog serves HTTPS on port 8000
    // unconditionally because it mounts the shared phantom_tls volume
    // and uses /tls/cert.pem (priority 1 in its _resolve_ssl_args).
    // The agent's entrypoint sets NODE_EXTRA_CA_CERTS=/tls/cert.pem
    // so the Next.js process trusts the self-signed cert; SAN covers
    // "xlog" hostname. An http:// fallback would hit
    // "Empty reply from server" (TLS handshake on plain HTTP).
    // Operator overrides via InstanceStore (preferred) and the env
    // var (compose) still win when set.
    XLOG_URL: xlogFromStore || clean(process.env.XLOG_URL) || "https://xlog:8000",
    MCP_TOOL_CACHE_TTL_MS: clean(process.env.MCP_TOOL_CACHE_TTL_MS) || "300000",
  };
}

/**
 * Derive the MCP's HTTP base URL from a full MCP_URL.
 * E.g. "http://phantom-mcp:8080/api/v1/stream/mcp" → "http://phantom-mcp:8080"
 *
 * Used by the /api/agent/* proxy routes that need to POST to admin
 * endpoints on the MCP at non-streamable paths.
 */
export function deriveMcpBaseUrl(mcpUrl: string): string {
  try {
    const u = new URL(mcpUrl);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}
