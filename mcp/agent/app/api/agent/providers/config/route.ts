/**
 * Provider config — read/write the LLM provider credentials operators
 * supply at /providers (the Spark-ported settings page).
 *
 * This route talks DIRECTLY to the MCP ProviderStore. Per the
 * canonical setup spec documented in /help/architecture#setup-wiring
 * (section "Setup Page Canonical Lifecycle Spec"), provider data
 * lives in ProviderStore (SecretStore-backed).
 *
 * Anthropic credentials (anthropicApiKey + anthropicCliKey) are
 * persisted: the PUT upserts a "primary-anthropic" provider instance,
 * and the chat-route CLI shell-out (/api/chat/cli) picks the
 * credential up via lib/anthropic-credentials.ts.
 *
 *   GET /api/agent/providers/config
 *     → fetches vertex + anthropic instances from ProviderStore
 *     → returns { providers: {...redacted view...}, configured: {...} }
 *
 *   PUT /api/agent/providers/config
 *     body { value: { vertex* fields, anthropic* fields } }
 *     → per provider: PUT update if instance exists, POST create otherwise
 *     → busts the per-provider chat-handler cache so the change is
 *       visible to the next chat dispatch immediately
 *
 * Field-name mapping (agent form → MCP instance):
 *   form.vertexProjectId          → instance.config.project_id
 *   form.vertexLocation           → instance.config.region
 *   form.vertexServiceAccountJson → instance.secrets.serviceAccountJson
 *   form.anthropicApiKey          → instance.secrets.api_key
 *   form.anthropicCliKey          → instance.secrets.cli_key
 */

import { NextResponse } from "next/server";

import { resolveMcp } from "@/lib/mcp-proxy";
import { bustVertexCredsCache } from "@/lib/vertex-credentials";
import { bustAnthropicCredsCache } from "@/lib/anthropic-credentials";

export const dynamic = "force-dynamic";

const PROVIDER_KEYS = [
  "anthropicApiKey",
  "anthropicCliKey",
  "vertexServiceAccountJson",
  "vertexProjectId",
  "vertexLocation",
] as const;
type ProviderKey = (typeof PROVIDER_KEYS)[number];

const SENSITIVE_KEYS: ReadonlySet<ProviderKey> = new Set<ProviderKey>([
  "anthropicApiKey",
  "anthropicCliKey",
  "vertexServiceAccountJson",
]);

const REDACTED = "***";

const VERTEX_PROVIDER_ID = "vertex";
const VERTEX_DEFAULT_INSTANCE_NAME = "primary-vertex";
const ANTHROPIC_PROVIDER_ID = "anthropic";
const ANTHROPIC_DEFAULT_INSTANCE_NAME = "primary-anthropic";

interface McpProviderInstance {
  id: string;
  provider_id: string;
  name: string;
  config: Record<string, unknown>;
  secrets: Record<string, unknown>;
  created_at: string;
}

/**
 * Fetch the first vertex provider instance (the convention is one
 * primary-vertex per install). Returns null if none configured yet.
 */
async function fetchVertexInstance(
  base: string,
  token: string,
): Promise<McpProviderInstance | null> {
  return fetchFirstInstance(base, token, VERTEX_PROVIDER_ID);
}

async function fetchAnthropicInstance(
  base: string,
  token: string,
): Promise<McpProviderInstance | null> {
  return fetchFirstInstance(base, token, ANTHROPIC_PROVIDER_ID);
}

async function fetchFirstInstance(
  base: string,
  token: string,
  providerId: string,
): Promise<McpProviderInstance | null> {
  const url = `${base}/api/v1/providers?provider_id=${encodeURIComponent(providerId)}`;
  const r = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) return null;
  const data = (await r.json().catch(() => ({}))) as {
    instances?: McpProviderInstance[];
  };
  const instances = data.instances ?? [];
  return instances.length > 0 ? instances[0] : null;
}

/**
 * Internal result shape for a single-provider upsert. Aggregated in
 * the PUT response under `mcp_sync.{vertex|anthropic}`.
 */
interface ProviderSyncResult {
  success: boolean;
  action?: "create" | "update" | "skipped";
  updated?: string;
  reason?: string;
  error?: string;
}

/**
 * Upsert a provider instance: PUT update if one exists, POST create
 * otherwise. Returns a structured result the PUT handler aggregates.
 *
 * `requiredOnCreate` lists fields that MUST be present on the first
 * create (vertex needs project_id + region + serviceAccountJson;
 * anthropic only needs one credential). When non-empty + missing,
 * the result reports a 400 reason so the operator sees what's
 * needed.
 */
async function upsertProviderInstance(
  base: string,
  token: string,
  args: {
    providerId: string;
    name: string;
    configPatch: Record<string, string>;
    secretsPatch: Record<string, string>;
    existing: McpProviderInstance | null;
    requiredOnCreate?: {
      keys: string[];
      failureReason: string;
      // "all" (default) means every listed key must be present;
      // "any" means at least one. Anthropic uses "any" because either
      // api_key (direct API) or cli_key (Pro/Max device-code OAuth) is
      // sufficient on first create. Vertex uses "all" because the SA
      // JSON, project_id, and region must all land in the same instance.
      mode?: "all" | "any";
    };
  },
): Promise<ProviderSyncResult> {
  const { providerId, name, configPatch, secretsPatch, existing, requiredOnCreate } = args;

  // Nothing to do.
  if (
    Object.keys(configPatch).length === 0 &&
    Object.keys(secretsPatch).length === 0
  ) {
    return {
      success: true,
      action: "skipped",
      reason: `no-op (no ${providerId} fields supplied)`,
    };
  }

  if (existing) {
    // Partial update. Merge configPatch onto existing.config so a
    // partial PUT doesn't blow away previously-set fields. secretsPatch
    // is replace-on-key (MCP-side honors the "***" sentinel but we
    // already filter that client-side — secretsPatch only contains
    // real values).
    const upstream = `${base}/api/v1/providers/${encodeURIComponent(existing.id)}`;
    const payload: { config?: Record<string, string>; secrets?: Record<string, string> } = {};
    if (Object.keys(configPatch).length > 0) {
      payload.config = {
        ...(existing.config as Record<string, string>),
        ...configPatch,
      };
    }
    if (Object.keys(secretsPatch).length > 0) {
      payload.secrets = secretsPatch;
    }
    const resp = await fetch(upstream, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15000),
    });
    const data = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
    if (!resp.ok) {
      return {
        success: false,
        error: (data.error as string) || `MCP update failed (HTTP ${resp.status})`,
      };
    }
    return { success: true, action: "update", updated: existing.id };
  }

  // No instance yet — POST create. Verify required fields if the
  // caller declared any.
  if (requiredOnCreate) {
    const merged = { ...configPatch, ...secretsPatch };
    const mode = requiredOnCreate.mode ?? "all";
    if (mode === "all") {
      // Vertex shape: every required key must be present.
      const missing = requiredOnCreate.keys.filter((k) => !merged[k]);
      if (missing.length > 0) {
        return { success: false, error: requiredOnCreate.failureReason };
      }
    } else {
      // "any" shape (Anthropic): at least one of the listed keys must
      // be present. Anthropic saves with only cli_key (the Pro/Max
      // device-code OAuth token) must succeed even when api_key is absent.
      const present = requiredOnCreate.keys.some((k) => !!merged[k]);
      if (!present) {
        return { success: false, error: requiredOnCreate.failureReason };
      }
    }
  }

  const upstream = `${base}/api/v1/providers`;
  const resp = await fetch(upstream, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      provider_id: providerId,
      name,
      config: configPatch,
      secrets: secretsPatch,
    }),
    signal: AbortSignal.timeout(15000),
  });
  const data = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
  if (!resp.ok) {
    return {
      success: false,
      error: (data.error as string) || `MCP create failed (HTTP ${resp.status})`,
    };
  }
  const created = data.instance as McpProviderInstance | undefined;
  return { success: true, action: "create", updated: created?.id };
}

export async function GET() {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const providers: Partial<Record<ProviderKey, string>> = {};
  const configured: Partial<Record<ProviderKey, boolean>> = {};

  // Read directly from ProviderStore — no setup.json fallback. Both
  // provider lookups run in parallel; failure on either falls back to
  // "not configured" without disturbing the other.
  const [vertex, anthropic] = await Promise.all([
    fetchVertexInstance(r.base, r.token).catch(() => null),
    fetchAnthropicInstance(r.base, r.token).catch(() => null),
  ]);

  if (vertex) {
    const project = vertex.config?.project_id;
    const region = vertex.config?.region;
    if (typeof project === "string" && project.length > 0) {
      providers.vertexProjectId = project;
      configured.vertexProjectId = true;
    }
    if (typeof region === "string" && region.length > 0) {
      providers.vertexLocation = region;
      configured.vertexLocation = true;
    }
    // The MCP redacts secrets to "***" already on its GET side, so
    // we just check presence and pass the sentinel through. The agent
    // never sees the cleartext on this read path.
    if (vertex.secrets?.serviceAccountJson !== undefined) {
      providers.vertexServiceAccountJson = REDACTED;
      configured.vertexServiceAccountJson = true;
    }
  }

  if (anthropic) {
    // Two independent secret slots: api_key (used by the chat-route's
    // future callAnthropic API path) and cli_key (used by the Claude
    // Code CLI shell-out at /api/chat/cli). Either or both can be set.
    if (anthropic.secrets?.api_key !== undefined) {
      providers.anthropicApiKey = REDACTED;
      configured.anthropicApiKey = true;
    }
    if (anthropic.secrets?.cli_key !== undefined) {
      providers.anthropicCliKey = REDACTED;
      configured.anthropicCliKey = true;
    }
  }

  // Spark page reads from `data.providers`. Wrap accordingly.
  return NextResponse.json({ providers, configured });
}

export async function PUT(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    value?: Partial<Record<ProviderKey, string>>;
  };
  const incoming = body.value ?? {};

  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  // Build per-provider patches. Each provider's fields are scoped
  // independently — the operator can supply a vertex-only update,
  // an anthropic-only update, or both. The redaction sentinel "***"
  // means "leave that secret alone" (form's pre-fill carries it
  // through for already-set credentials); skip those values.
  const vertexConfigPatch: Record<string, string> = {};
  const vertexSecretsPatch: Record<string, string> = {};
  const anthropicSecretsPatch: Record<string, string> = {};

  // ── Vertex ─────────────────────────────────────────────────
  if (typeof incoming.vertexProjectId === "string" && incoming.vertexProjectId.trim()) {
    vertexConfigPatch.project_id = incoming.vertexProjectId.trim();
  }
  if (typeof incoming.vertexLocation === "string" && incoming.vertexLocation.trim()) {
    vertexConfigPatch.region = incoming.vertexLocation.trim();
  }
  if (
    typeof incoming.vertexServiceAccountJson === "string" &&
    incoming.vertexServiceAccountJson !== "" &&
    incoming.vertexServiceAccountJson !== REDACTED
  ) {
    vertexSecretsPatch.serviceAccountJson = incoming.vertexServiceAccountJson;
  }

  // ── Anthropic ──────────────────────────────────────────────
  if (
    typeof incoming.anthropicApiKey === "string" &&
    incoming.anthropicApiKey !== "" &&
    incoming.anthropicApiKey !== REDACTED
  ) {
    anthropicSecretsPatch.api_key = incoming.anthropicApiKey.trim();
  }
  if (
    typeof incoming.anthropicCliKey === "string" &&
    incoming.anthropicCliKey !== "" &&
    incoming.anthropicCliKey !== REDACTED
  ) {
    anthropicSecretsPatch.cli_key = incoming.anthropicCliKey.trim();
  }

  // Short-circuit if nothing to do.
  if (
    Object.keys(vertexConfigPatch).length === 0 &&
    Object.keys(vertexSecretsPatch).length === 0 &&
    Object.keys(anthropicSecretsPatch).length === 0
  ) {
    return NextResponse.json({
      ok: true,
      mcp_sync: { success: true, skipped: true, reason: "no-op (no fields to update)" },
    });
  }

  // Fetch existing instances in parallel.
  const [vertexExisting, anthropicExisting] = await Promise.all([
    fetchVertexInstance(r.base, r.token).catch(() => null),
    fetchAnthropicInstance(r.base, r.token).catch(() => null),
  ]);

  // Process per-provider upserts in parallel. Failure on one doesn't
  // abort the other — the response carries both results so the
  // operator sees exactly which provider succeeded.
  const [vertexResult, anthropicResult] = await Promise.all([
    upsertProviderInstance(r.base, r.token, {
      providerId: VERTEX_PROVIDER_ID,
      name: VERTEX_DEFAULT_INSTANCE_NAME,
      configPatch: vertexConfigPatch,
      secretsPatch: vertexSecretsPatch,
      existing: vertexExisting,
      requiredOnCreate: {
        keys: ["project_id", "region", "serviceAccountJson"],
        failureReason:
          "Vertex provider is not yet configured. Project ID, region, " +
          "and service account JSON are all required to create the " +
          "primary-vertex instance for the first time.",
      },
    }),
    upsertProviderInstance(r.base, r.token, {
      providerId: ANTHROPIC_PROVIDER_ID,
      name: ANTHROPIC_DEFAULT_INSTANCE_NAME,
      configPatch: {},
      secretsPatch: anthropicSecretsPatch,
      existing: anthropicExisting,
      requiredOnCreate: {
        // Anthropic needs at least one credential on first create —
        // either api_key (for API use) or cli_key (for CLI shell-out
        // via Pro/Max device-code OAuth). The MCP store fails if
        // secrets is empty, but accepting only ONE is the intended
        // semantic.
        keys: ["api_key", "cli_key"],
        mode: "any",
        failureReason:
          "Anthropic provider is not yet configured. Supply either an " +
          "API key (for direct API use) or a Claude Code CLI key (for " +
          "the /api/chat/cli shell-out endpoint) to create the " +
          "primary-anthropic instance for the first time.",
      },
    }),
  ]);

  // Bust per-provider caches so the next chat / CLI dispatch sees the
  // updated credentials immediately, not after the 30-second TTL.
  if (vertexResult.success && vertexResult.action !== "skipped") {
    bustVertexCredsCache();
  }
  if (anthropicResult.success && anthropicResult.action !== "skipped") {
    bustAnthropicCredsCache();
  }

  // Aggregate response. Any failure → HTTP 400 with both results so
  // the form can surface per-provider errors. All success → 200.
  const allSuccess = vertexResult.success && anthropicResult.success;
  return NextResponse.json(
    {
      ok: allSuccess,
      mcp_sync: {
        vertex: vertexResult,
        anthropic: anthropicResult,
      },
    },
    { status: allSuccess ? 200 : 400 },
  );
}
