/**
 * Provider config — read/write the LLM provider credentials operators
 * supply at /providers (the Spark-ported settings page).
 *
 * This route talks DIRECTLY to the MCP ProviderStore. Per the
 * canonical setup spec documented in /help/architecture#setup-wiring
 * (section "Setup Page Canonical Lifecycle Spec"), provider data
 * lives in ProviderStore (SecretStore-backed).
 *
 * The Anthropic and OpenAI credentials are persisted the same way: the PUT
 * upserts a "primary-anthropic" / "primary-openai" provider instance, and
 * lib/providers/credentials.ts reads it back. A base URL passes the
 * outbound-URL guard (lib/providers/url-guard.ts) before it is saved, and
 * again on every call that uses it.
 *
 * A saved API key is only ever sent to the base URL it was saved with, so
 * changing the base URL of a provider that already holds a key requires the
 * key to be typed again in the same request. Otherwise a base URL pointing at
 * a host the operator does not control would receive the stored key on the
 * next call. This holds for every provider with a base URL.
 *
 *   GET /api/agent/providers/config
 *     → fetches vertex + anthropic + openai instances from ProviderStore
 *     → returns { providers: {...redacted view...}, configured: {...} }
 *
 *   PUT /api/agent/providers/config
 *     body { value: { vertex* fields, anthropic* fields, openai* fields } }
 *     → per provider: PUT update if instance exists, POST create otherwise
 *     → busts the per-provider chat-handler cache so the change is
 *       visible to the next chat dispatch immediately
 *
 * Field-name mapping (agent form → MCP instance):
 *   form.vertexProjectId          → instance.config.project_id
 *   form.vertexLocation           → instance.config.region
 *   form.vertexServiceAccountJson → instance.secrets.serviceAccountJson
 *   form.anthropicApiKey          → instance.secrets.api_key
 *   form.anthropicBaseUrl         → instance.config.base_url (empty clears it)
 *   form.openaiApiKey             → instance.secrets.api_key
 *   form.openaiBaseUrl            → instance.config.base_url (empty clears it)
 *   form.openaiOrganization       → instance.config.organization (empty clears it)
 *   form.openaiProject            → instance.config.project (empty clears it)
 */

import { NextResponse } from "next/server";

import { resolveMcp } from "@/lib/mcp-proxy";
import { mcpBlockedHosts } from "@/lib/mcp-host";
import { bustVertexCredsCache } from "@/lib/vertex-credentials";
import { normalizeBaseUrl } from "@/lib/providers/connection-test";
import { bustProviderCredsCache } from "@/lib/providers/credentials";
import { ProviderError } from "@/lib/providers/errors";
import { ANTHROPIC_DEFAULT_BASE, isValidScopeId, OPENAI_DEFAULT_BASE } from "@/lib/providers/registry/live";
import { bustModelRegistryCache } from "@/lib/providers/registry/registry";
import { assertSafeBaseUrl } from "@/lib/providers/url-guard";

export const dynamic = "force-dynamic";

const PROVIDER_KEYS = [
  "anthropicApiKey",
  "anthropicBaseUrl",
  "openaiApiKey",
  "openaiOrganization",
  "openaiProject",
  "openaiBaseUrl",
  "vertexServiceAccountJson",
  "vertexProjectId",
  "vertexLocation",
] as const;
type ProviderKey = (typeof PROVIDER_KEYS)[number];

const SENSITIVE_KEYS: ReadonlySet<ProviderKey> = new Set<ProviderKey>([
  "anthropicApiKey",
  "openaiApiKey",
  "vertexServiceAccountJson",
]);

const REDACTED = "***";

const VERTEX_PROVIDER_ID = "vertex";
const VERTEX_DEFAULT_INSTANCE_NAME = "primary-vertex";

/**
 * The model providers that are an API key plus an optional base URL (and, for
 * OpenAI, an optional organization and project). One table drives the read,
 * the validation and the upsert for all of them.
 */
interface KeyedProvider {
  id: "anthropic" | "openai";
  instanceName: string;
  label: string;
  defaultBase: string;
  fields: {
    apiKey: ProviderKey;
    baseUrl: ProviderKey;
    organization?: ProviderKey;
    project?: ProviderKey;
  };
}

const KEYED_PROVIDERS: readonly KeyedProvider[] = [
  {
    id: "anthropic",
    instanceName: "primary-anthropic",
    label: "Anthropic",
    defaultBase: ANTHROPIC_DEFAULT_BASE,
    fields: { apiKey: "anthropicApiKey", baseUrl: "anthropicBaseUrl" },
  },
  {
    id: "openai",
    instanceName: "primary-openai",
    label: "OpenAI",
    defaultBase: OPENAI_DEFAULT_BASE,
    fields: {
      apiKey: "openaiApiKey",
      baseUrl: "openaiBaseUrl",
      organization: "openaiOrganization",
      project: "openaiProject",
    },
  },
];

interface McpProviderInstance {
  id: string;
  provider_id: string;
  name: string;
  config: Record<string, unknown>;
  secrets: Record<string, unknown>;
  created_at: string;
}

/**
 * Vet an operator-typed base URL before it is stored. Syntax, scheme and host
 * rules, and the addresses it resolves to, are checked by the outbound-URL
 * guard. A host that does not resolve right now is still accepted: the rules
 * that can be judged without DNS have passed, and the guard runs again on
 * every call.
 */
async function vetBaseUrl(raw: string): Promise<{ value: string } | { error: string }> {
  try {
    return { value: await assertSafeBaseUrl(raw, { blockedHosts: mcpBlockedHosts() }) };
  } catch (err) {
    if (err instanceof ProviderError && err.kind === "network") {
      return { value: raw.replace(/\/+$/, "") };
    }
    return { error: err instanceof ProviderError ? err.message : "The base URL was not accepted." };
  }
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
 * anthropic only needs its API key). When non-empty + missing,
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
    // Every required key must be present.
    const missing = requiredOnCreate.keys.filter((k) => !merged[k]);
    if (missing.length > 0) {
      return { success: false, error: requiredOnCreate.failureReason };
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

/** Surface one keyed provider's stored instance in the redacted GET view. */
function describeKeyedProvider(
  def: KeyedProvider,
  instance: McpProviderInstance | null,
  providers: Partial<Record<ProviderKey, string>>,
  configured: Partial<Record<ProviderKey, boolean>>,
): void {
  if (!instance) return;
  // Only api_key is surfaced. Any other secret slot on the instance is ignored
  // and never echoed; the MCP redacts it on its GET side already.
  if (instance.secrets?.api_key !== undefined) {
    providers[def.fields.apiKey] = REDACTED;
    configured[def.fields.apiKey] = true;
  }
  const config: Array<[ProviderKey | undefined, string]> = [
    [def.fields.baseUrl, "base_url"],
    [def.fields.organization, "organization"],
    [def.fields.project, "project"],
  ];
  for (const [field, configKey] of config) {
    if (!field) continue;
    const value = instance.config?.[configKey];
    if (typeof value === "string" && value.length > 0) {
      providers[field] = value;
      configured[field] = true;
    }
  }
}

export async function GET() {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const providers: Partial<Record<ProviderKey, string>> = {};
  const configured: Partial<Record<ProviderKey, boolean>> = {};

  // Read directly from ProviderStore — no setup.json fallback. All provider
  // lookups run in parallel; failure on one falls back to "not configured"
  // without disturbing the others.
  const [vertex, ...keyed] = await Promise.all([
    fetchVertexInstance(r.base, r.token).catch(() => null),
    ...KEYED_PROVIDERS.map((def) => fetchFirstInstance(r.base, r.token, def.id).catch(() => null)),
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

  KEYED_PROVIDERS.forEach((def, i) => describeKeyedProvider(def, keyed[i], providers, configured));

  // Spark page reads from `data.providers`. Wrap accordingly.
  return NextResponse.json({ providers, configured });
}

interface KeyedPatch {
  configPatch: Record<string, string>;
  secretsPatch: Record<string, string>;
}

/**
 * Refuse a typed secret that the MCP store would read as a reference to another
 * secret. A value starting with "/" is stored as a SecretStore path and later
 * resolved to its plaintext, so a typed key of "/ui/auth/admin/password_hash"
 * would be sent to the provider's base URL as the bearer token. An API key
 * never starts with "/" or contains whitespace or a newline (a paste artefact
 * that also breaks the Authorization header).
 */
function vetTypedKey(label: string, value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.startsWith("/")) {
    return `The ${label} API key cannot start with "/". Paste the key itself, not a path.`;
  }
  if (/\s/.test(trimmed)) {
    return `The ${label} API key cannot contain spaces or line breaks. Paste only the key.`;
  }
  return null;
}

/**
 * Turn one keyed provider's form fields into config and secret patches, or an
 * error that stops the whole save.
 *
 * The redaction sentinel "***" means "leave the saved key alone". A field that
 * is present is a change: a value sets it, an empty string clears it. The base
 * URL is vetted by the outbound-URL guard, and changing it away from the saved
 * one while a key is stored demands that the key is typed again in this same
 * request.
 */
async function buildKeyedPatch(
  def: KeyedProvider,
  incoming: Partial<Record<ProviderKey, string>>,
  existing: McpProviderInstance | null,
): Promise<KeyedPatch | { error: string }> {
  const configPatch: Record<string, string> = {};
  const secretsPatch: Record<string, string> = {};

  const typedKey = incoming[def.fields.apiKey];
  if (typeof typedKey === "string" && typedKey !== "" && typedKey !== REDACTED) {
    const keyError = vetTypedKey(def.label, typedKey);
    if (keyError) return { error: keyError };
    secretsPatch.api_key = typedKey.trim();
  }

  const typedBase = incoming[def.fields.baseUrl];
  if (typeof typedBase === "string") {
    const typed = typedBase.trim();
    if (typed === "") {
      configPatch.base_url = "";
    } else {
      const vetted = await vetBaseUrl(typed);
      if ("error" in vetted) return { error: vetted.error };
      configPatch.base_url = vetted.value;
    }
    const keyStored = existing?.secrets?.api_key !== undefined;
    if (keyStored && secretsPatch.api_key === undefined) {
      const savedBase = normalizeBaseUrl(String(existing?.config?.base_url ?? "") || def.defaultBase);
      const nextBase = normalizeBaseUrl(configPatch.base_url || def.defaultBase);
      if (savedBase !== nextBase) {
        return {
          error:
            `Enter the ${def.label} API key again to change the base URL. ` +
            "A saved key is only sent to the base URL it was saved with.",
        };
      }
    }
  }

  const scoped: Array<[ProviderKey | undefined, string, string]> = [
    [def.fields.organization, "organization", "organization"],
    [def.fields.project, "project", "project"],
  ];
  for (const [field, configKey, noun] of scoped) {
    if (!field) continue;
    const value = incoming[field];
    if (typeof value !== "string") continue;
    const typed = value.trim();
    if (typed !== "" && !isValidScopeId(typed)) {
      return { error: `The ${def.label} ${noun} must be an identifier such as "${noun === "project" ? "proj_..." : "org-..."}".` };
    }
    configPatch[configKey] = typed;
  }
  return { configPatch, secretsPatch };
}

export async function PUT(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    value?: Partial<Record<ProviderKey, string>>;
  };
  const incoming = body.value ?? {};

  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  // Build per-provider patches. Each provider's fields are scoped
  // independently — the operator can supply a vertex-only update, an
  // anthropic-only update, or any mix. The redaction sentinel "***" means
  // "leave that secret alone" (form's pre-fill carries it through for
  // already-set credentials); skip those values.
  const vertexConfigPatch: Record<string, string> = {};
  const vertexSecretsPatch: Record<string, string> = {};

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
    // The MCP store reads a value starting with "/" as a path to another
    // secret. The service-account JSON is an object, never a path.
    if (incoming.vertexServiceAccountJson.trimStart().startsWith("/")) {
      const error = 'The Vertex service account JSON cannot start with "/". Paste the JSON itself, not a file path.';
      return NextResponse.json(
        { ok: false, error, mcp_sync: { vertex: { success: false, error } } },
        { status: 400 },
      );
    }
    vertexSecretsPatch.serviceAccountJson = incoming.vertexServiceAccountJson;
  }

  // The stored instances come first: the base-URL rule compares against them.
  const [vertexExisting, ...keyedExisting] = await Promise.all([
    fetchVertexInstance(r.base, r.token).catch(() => null),
    ...KEYED_PROVIDERS.map((def) => fetchFirstInstance(r.base, r.token, def.id).catch(() => null)),
  ]);

  // ── Anthropic and OpenAI ───────────────────────────────────
  // A rejected value stops the whole save.
  const keyedPatches: KeyedPatch[] = [];
  for (let i = 0; i < KEYED_PROVIDERS.length; i++) {
    const def = KEYED_PROVIDERS[i];
    const patch = await buildKeyedPatch(def, incoming, keyedExisting[i]);
    if ("error" in patch) {
      return NextResponse.json(
        {
          ok: false,
          error: patch.error,
          mcp_sync: { [def.id]: { success: false, error: patch.error } },
        },
        { status: 400 },
      );
    }
    keyedPatches.push(patch);
  }

  // Short-circuit if nothing to do.
  const nothingToSave =
    Object.keys(vertexConfigPatch).length === 0 &&
    Object.keys(vertexSecretsPatch).length === 0 &&
    keyedPatches.every(
      (p) => Object.keys(p.configPatch).length === 0 && Object.keys(p.secretsPatch).length === 0,
    );
  if (nothingToSave) {
    return NextResponse.json({
      ok: true,
      mcp_sync: { success: true, skipped: true, reason: "no-op (no fields to update)" },
    });
  }

  // Process per-provider upserts in parallel. Failure on one doesn't
  // abort the others — the response carries every result so the
  // operator sees exactly which provider succeeded.
  const [vertexResult, ...keyedResults] = await Promise.all([
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
    ...KEYED_PROVIDERS.map((def, i) =>
      upsertProviderInstance(r.base, r.token, {
        providerId: def.id,
        name: def.instanceName,
        configPatch: keyedPatches[i].configPatch,
        secretsPatch: keyedPatches[i].secretsPatch,
        existing: keyedExisting[i],
        requiredOnCreate: {
          // The API key is needed on first create. The MCP store fails if
          // secrets is empty.
          keys: ["api_key"],
          failureReason:
            `${def.label} provider is not yet configured. Supply an API ` +
            `key to create the ${def.instanceName} instance for the first time.`,
        },
      }),
    ),
  ]);

  // Bust per-provider caches so the next chat dispatch sees the
  // updated credentials immediately, not after the 30-second TTL.
  // The model registry's cached live lists are keyed by credential, so a
  // changed credential would miss them anyway; busting also drops a failure
  // remembered under the old one, so a corrected key is tried at once.
  if (vertexResult.success && vertexResult.action !== "skipped") {
    bustVertexCredsCache();
    bustProviderCredsCache("vertex");
    bustModelRegistryCache("vertex");
  }
  KEYED_PROVIDERS.forEach((def, i) => {
    const result = keyedResults[i];
    if (result.success && result.action !== "skipped") {
      bustProviderCredsCache(def.id);
      bustModelRegistryCache(def.id);
    }
  });

  // Aggregate response. Any failure → HTTP 400 with every result so
  // the form can surface per-provider errors. All success → 200.
  const allSuccess = vertexResult.success && keyedResults.every((result) => result.success);
  return NextResponse.json(
    {
      ok: allSuccess,
      mcp_sync: {
        vertex: vertexResult,
        ...Object.fromEntries(KEYED_PROVIDERS.map((def, i) => [def.id, keyedResults[i]])),
      },
    },
    { status: allSuccess ? 200 : 400 },
  );
}
