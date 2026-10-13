/**
 * Server-side wiring of the model registry: the shared registry instance with
 * its audit sink and blocked-host list, the install's default model setting
 * (read from the MCP settings store with a short cache), and the one function
 * that turns a request into the model a turn runs on. Imported by the chat
 * route and the models, settings and jobs routes; never by client code.
 */

import { callMcpServer } from "@/lib/mcp-proxy";
import { mcpBlockedHosts } from "@/lib/mcp-host";
import { getEffectiveRuntimeConfig, type EffectiveRuntimeConfig } from "@/lib/runtime-config";
import { resolveProviderCreds } from "@/lib/providers/credentials";
import {
  bodyTouchesModel,
  resolveChatModel,
  validateModelWrite,
  type FieldRejection,
  type ModelWriteKind,
  type TurnModelInput,
  type TurnModelResult,
} from "@/lib/providers/model-resolution";
import type { ModelEntry } from "@/lib/providers/registry/types";
import {
  configureModelRegistry,
  getModelRegistry,
  type AuditSink,
  type ModelRegistry,
} from "@/lib/providers/registry/registry";
import { listRegistryEntries, serveModels, type ApiModel } from "@/lib/providers/registry/serve";

const auditSink: AuditSink = async (action, row) => {
  await callMcpServer("/api/v1/audit", {
    method: "POST",
    body: {
      action,
      target: row.target,
      status: row.status,
      duration_ms: row.durationMs,
      metadata: row.metadata,
    },
  });
};

let configured = false;

export function serverModelRegistry(): ModelRegistry {
  if (!configured) {
    configureModelRegistry({ audit: auditSink, blockedHosts: mcpBlockedHosts() });
    configured = true;
  }
  return getModelRegistry();
}

/* ─── The install default (settings key `defaultModel`) ─────── */

const DEFAULT_MODEL_TTL_MS = 30_000;
let defaultModelCache: { value: string | undefined; expiresAt: number } | null = null;

/**
 * The effective `defaultModel` setting: the operator's override, else the
 * manifest default. Read from the MCP settings store (the one home for this
 * value) and cached for 30 s; `bustInstallDefaultModelCache` drops the cache
 * when the settings proxy writes. Undefined when the store cannot be read and
 * nothing is cached, in which case the derived default serves.
 */
export async function readInstallDefaultModel(): Promise<string | undefined> {
  const now = Date.now();
  if (defaultModelCache && defaultModelCache.expiresAt > now) return defaultModelCache.value;
  try {
    const snapshot = await callMcpServer<{ effective?: Record<string, unknown> }>("/api/v1/settings", {
      timeoutMs: 5_000,
    });
    const raw = snapshot?.effective?.defaultModel;
    const value = typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
    defaultModelCache = { value, expiresAt: now + DEFAULT_MODEL_TTL_MS };
    return value;
  } catch {
    return defaultModelCache?.value;
  }
}

export function bustInstallDefaultModelCache(): void {
  defaultModelCache = null;
}

/* ─── Resolution ───────────────────────────────────────────── */

/** Registry entries (retired ones included) for the credentials this install has. */
export async function loadRegistryEntries(
  runtime?: EffectiveRuntimeConfig,
): Promise<ModelEntry[]> {
  return await listRegistryEntries({
    registry: serverModelRegistry(),
    runtime: runtime ?? (await getEffectiveRuntimeConfig()),
    resolveCreds: (provider) => resolveProviderCreds(provider),
    includeRetired: true,
  });
}

/**
 * The model one request runs on: header, else session preference, else the
 * install default, else the derived default; or the reason none can serve.
 */
export async function resolveModelForRequest(
  input: Omit<TurnModelInput, "installDefault">,
  runtime?: EffectiveRuntimeConfig,
): Promise<{ result: TurnModelResult; entries: ModelEntry[]; installDefault: string | undefined }> {
  const [entries, installDefault] = await Promise.all([
    loadRegistryEntries(runtime),
    readInstallDefaultModel(),
  ]);
  return { result: resolveChatModel({ ...input, installDefault }, entries), entries, installDefault };
}

/**
 * Check the model in a settings or job write before it is forwarded to the MCP.
 * Returns the body to forward (the model rewritten to its canonical ref) or the
 * 400 to answer with. A body that is not JSON, or writes no model, is returned
 * untouched: the MCP stays the authority on everything else.
 */
export async function checkModelWrite(
  kind: ModelWriteKind,
  raw: string,
): Promise<{ ok: true; body: string } | FieldRejection> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: true, body: raw };
  }
  if (!bodyTouchesModel(kind, parsed)) return { ok: true, body: raw };
  const verdict = validateModelWrite(kind, parsed, await loadRegistryEntries());
  return verdict.ok ? { ok: true, body: JSON.stringify(verdict.body) } : verdict;
}

/** GET /api/agent/models: the merged registry as the UI and the agent read it. */
export async function listModelsForApi(opts: { includeRetired?: boolean } = {}): Promise<ApiModel[]> {
  const runtime = await getEffectiveRuntimeConfig();
  return await serveModels({
    registry: serverModelRegistry(),
    runtime,
    resolveCreds: (provider) => resolveProviderCreds(provider),
    installDefault: await readInstallDefaultModel(),
    includeRetired: opts.includeRetired,
  });
}
