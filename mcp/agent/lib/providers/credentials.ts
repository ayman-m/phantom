/**
 * Provider credentials, read from the MCP ProviderStore.
 *
 * `resolveProviderCreds(providerId)` is the one reader for every model
 * provider's stored credentials. It asks the embedded MCP over loopback for the
 * provider's instance with `?include_secrets=true` (a flag the MCP honours only
 * for loopback callers; the agent's own proxy strips it from outside requests)
 * and maps the instance onto the explicit `ProviderCreds` object adapters take.
 * Adapters never read the environment or the store themselves.
 *
 * "Configured" means a non-empty secret on a stored instance, which is the
 * evidence the system can observe. There is no environment fallback: the store
 * is the one home for these values.
 *
 *   anthropic  secrets.api_key; config.base_url
 *   openai     secrets.api_key; config.organization, config.project, config.base_url
 *   vertex     secrets.serviceAccountJson
 *
 * A 30-second cache amortizes the loopback round trip; `bustProviderCredsCache`
 * (called when the Providers page saves) drops it so a change is seen at once.
 * A transport failure resolves to null (not configured) rather than throwing,
 * and is not logged: every chat dispatch would repeat the line.
 *
 * The MCP address and token are read from MCP_URL and MCP_TOKEN directly. They
 * are bundle-internal, and going through the runtime-config helpers would be a
 * circular import (the runtime config calls the credential readers).
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import type { ProviderCreds, ProviderId } from './types.ts';

const CACHE_TTL_MS = 30_000;
const REQUEST_TIMEOUT_MS = 8_000;

export interface McpCoordinates {
  base: string;
  token: string;
}

export interface CredentialDeps {
  fetch?: typeof fetch;
  /** Defaults to MCP_URL / MCP_TOKEN from the environment. */
  mcp?: () => McpCoordinates | null;
  now?: () => number;
}

interface McpProviderInstance {
  id: string;
  provider_id: string;
  config?: Record<string, unknown>;
  secrets?: Record<string, unknown>;
}

function nonEmpty(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim().length > 0 ? v : undefined;
}

/** Map a stored instance onto adapter credentials; null when its secret is empty. */
export function credsFromInstance(providerId: ProviderId, instance: McpProviderInstance): ProviderCreds | null {
  const secrets = instance.secrets ?? {};
  const config = instance.config ?? {};
  if (providerId === 'vertex') {
    const serviceAccountJson = nonEmpty(secrets.serviceAccountJson);
    return serviceAccountJson ? { serviceAccountJson } : null;
  }
  const apiKey = nonEmpty(secrets.api_key);
  if (!apiKey) return null;
  const creds: ProviderCreds = { apiKey };
  const baseUrl = nonEmpty(config.base_url);
  if (baseUrl) creds.baseUrl = baseUrl.trim();
  if (providerId === 'openai') {
    const organization = nonEmpty(config.organization);
    const project = nonEmpty(config.project);
    if (organization) creds.organization = organization.trim();
    if (project) creds.project = project.trim();
  }
  return creds;
}

export function mcpCoordinatesFromEnv(): McpCoordinates | null {
  const token = (process.env.MCP_TOKEN || '').trim();
  if (!token) return null;
  const url = (process.env.MCP_URL || 'http://localhost:8080/api/v1/stream/mcp').trim();
  try {
    const u = new URL(url);
    return { base: `${u.protocol}//${u.host}`, token };
  } catch {
    return null;
  }
}

async function readFromStore(providerId: ProviderId, deps: CredentialDeps): Promise<ProviderCreds | null> {
  const coords = (deps.mcp ?? mcpCoordinatesFromEnv)();
  if (!coords) return null;
  const doFetch = deps.fetch ?? ((input: string, init?: RequestInit) => fetch(input, init));
  const headers = { Authorization: `Bearer ${coords.token}` };
  try {
    const list = await doFetch(`${coords.base}/api/v1/providers?provider_id=${encodeURIComponent(providerId)}`, {
      headers,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!list.ok) return null;
    const listed = (await list.json().catch(() => ({}))) as { instances?: McpProviderInstance[] };
    const first = listed.instances?.[0];
    if (!first) return null;
    const detail = await doFetch(
      `${coords.base}/api/v1/providers/${encodeURIComponent(first.id)}?include_secrets=true`,
      { headers, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
    );
    if (!detail.ok) return null;
    const body = (await detail.json().catch(() => ({}))) as { instance?: McpProviderInstance };
    return body.instance ? credsFromInstance(providerId, body.instance) : null;
  } catch {
    return null;
  }
}

const cache = new Map<ProviderId, { value: ProviderCreds | null; expiresAt: number }>();

/** The provider's stored credentials, or null when it is not configured. */
export async function resolveProviderCreds(
  providerId: ProviderId,
  deps: CredentialDeps = {},
): Promise<ProviderCreds | null> {
  const now = (deps.now ?? Date.now)();
  const hit = cache.get(providerId);
  if (hit && hit.expiresAt > now) return hit.value;
  const value = await readFromStore(providerId, deps);
  cache.set(providerId, { value, expiresAt: now + CACHE_TTL_MS });
  return value;
}

/** Drop cached credentials (one provider, or all) after the Providers page saves. */
export function bustProviderCredsCache(providerId?: ProviderId): void {
  if (providerId) cache.delete(providerId);
  else cache.clear();
}
