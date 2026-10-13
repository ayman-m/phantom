/**
 * Live model-list fetchers.
 *
 *   Anthropic   GET {base}/v1/models?limit=1000, paged with after_id
 *   OpenAI      GET {base}/models
 *   Gemini API  GET models, paged with pageToken (only when an API key exists)
 *
 * Vertex has no usable list, so `fetchLiveModels('vertex', ...)` without a
 * Gemini API key returns null: the curated catalog is authoritative there.
 *
 * Plain `fetch`, injectable. Credentials come in as an explicit object; this
 * module reads no environment. Every request goes through `guardedFetch`
 * (https only, no redirects, a deadline), the operator-set base URL is vetted
 * by `assertSafeBaseUrl`, and error text reflects only a JSON `error.message`
 * (never a raw body), redacted. URLs are never put in error text, because the
 * Gemini key could ride in one.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { ProviderError } from '../errors.ts';
import type { LiveCapabilities, LiveModel, ProviderCreds, ProviderId } from '../types.ts';
import {
  assertSafeBaseUrl,
  guardedFetch,
  type GuardedFetchDeps,
  type UrlGuardDeps,
} from '../url-guard.ts';

export const ANTHROPIC_DEFAULT_BASE = 'https://api.anthropic.com';
export const OPENAI_DEFAULT_BASE = 'https://api.openai.com/v1';
export const GEMINI_API_LIST_BASE = 'https://generativelanguage.googleapis.com/v1beta';
const ANTHROPIC_VERSION = '2023-06-01';
const MAX_PAGES = 10;

export interface LiveFetchDeps extends GuardedFetchDeps, UrlGuardDeps {}

type Json = Record<string, unknown>;

function isObject(v: unknown): v is Json {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

function posInt(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.floor(v) : undefined;
}

/** Turn a failed list response into a ProviderError without reflecting a raw body. */
async function listFailure(response: Response, provider: string): Promise<ProviderError> {
  let detail = '';
  try {
    const body: unknown = await response.json();
    const error = isObject(body) && isObject(body.error) ? body.error : undefined;
    const message = error ? str(error.message) : undefined;
    if (message) detail = `: ${message}`;
  } catch {
    // A non-JSON body is not echoed.
  }
  const status = response.status;
  const retryAfter = Number(response.headers.get('retry-after'));
  const requestId = response.headers.get('request-id') ?? response.headers.get('x-request-id') ?? undefined;
  const base = { status, requestId, message: `${provider} model list failed (HTTP ${status})${detail}` };
  if (status === 401) return new ProviderError({ ...base, kind: 'auth' });
  if (status === 403) return new ProviderError({ ...base, kind: 'permission' });
  if (status === 429) {
    return new ProviderError({
      ...base,
      kind: 'rate_limit',
      retryable: true,
      retryAfterMs: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : undefined,
    });
  }
  if (status === 529) return new ProviderError({ ...base, kind: 'overloaded', retryable: true });
  if (status >= 500) return new ProviderError({ ...base, kind: 'unavailable', retryable: true });
  return new ProviderError({ ...base, kind: 'invalid_request' });
}

async function getJson(
  url: string,
  headers: Record<string, string>,
  provider: string,
  deps: LiveFetchDeps,
): Promise<Json> {
  const response = await guardedFetch(url, { method: 'GET', headers }, deps);
  if (!response.ok) throw await listFailure(response, provider);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ProviderError({ kind: 'unknown', message: `${provider} model list was not JSON`, status: response.status });
  }
  if (!isObject(body)) {
    throw new ProviderError({ kind: 'unknown', message: `${provider} model list had an unexpected shape`, status: response.status });
  }
  return body;
}

function requireKey(creds: ProviderCreds, provider: string): string {
  const key = creds.apiKey?.trim();
  if (!key) throw new ProviderError({ kind: 'auth', message: `No ${provider} API key is configured.` });
  return key;
}

/* ─── Anthropic ─────────────────────────────────────────────── */

function supportedFlag(v: unknown): boolean | undefined {
  if (typeof v === 'boolean') return v;
  if (isObject(v) && typeof v.supported === 'boolean') return v.supported;
  return undefined;
}

function parseEfforts(effort: unknown): string[] | undefined {
  if (Array.isArray(effort)) return effort.filter((e): e is string => typeof e === 'string');
  if (!isObject(effort)) return undefined;
  const out: string[] = [];
  for (const [level, v] of Object.entries(effort)) {
    if (supportedFlag(v) === true) out.push(level);
  }
  return out;
}

export function parseAnthropicModel(item: unknown): LiveModel | null {
  if (!isObject(item)) return null;
  const id = str(item.id);
  if (!id) return null;
  const out: LiveModel = { id };
  const displayName = str(item.display_name);
  if (displayName) out.displayName = displayName;
  const ctx = posInt(item.max_input_tokens);
  if (ctx) out.contextWindow = ctx;
  const maxOut = posInt(item.max_tokens);
  if (maxOut) out.maxOutput = maxOut;
  const lifecycle = str(item.lifecycle);
  if (lifecycle === 'active' || lifecycle === 'deprecated' || lifecycle === 'retired') out.lifecycle = lifecycle;
  const retiresAt = str(item.retires_at);
  if (retiresAt) out.retiresAt = retiresAt;

  const caps = isObject(item.capabilities) ? item.capabilities : undefined;
  if (caps) {
    const live: LiveCapabilities = {};
    const types = isObject(caps.thinking) && isObject(caps.thinking.types) ? caps.thinking.types : undefined;
    if (types) {
      const adaptive = supportedFlag(types.adaptive);
      const enabled = supportedFlag(types.enabled);
      const disabled = supportedFlag(types.disabled);
      if (adaptive !== undefined) live.thinkingAdaptive = adaptive;
      if (enabled !== undefined) live.thinkingEnabled = enabled;
      if (disabled !== undefined) live.thinkingDisabled = disabled;
    }
    const efforts = parseEfforts(caps.effort);
    if (efforts) live.efforts = efforts;
    if (Object.keys(live).length > 0) out.capabilities = live;
  }
  return out;
}

export async function fetchAnthropicModels(creds: ProviderCreds, deps: LiveFetchDeps = {}): Promise<LiveModel[]> {
  const key = requireKey(creds, 'Anthropic');
  const base = await assertSafeBaseUrl(creds.baseUrl?.trim() || ANTHROPIC_DEFAULT_BASE, deps);
  const headers = {
    Authorization: `Bearer ${key}`,
    'anthropic-version': ANTHROPIC_VERSION,
    Accept: 'application/json',
  };
  const out: LiveModel[] = [];
  let afterId: string | undefined;
  for (let page = 0; page < MAX_PAGES; page++) {
    const query = new URLSearchParams({ limit: '1000' });
    if (afterId) query.set('after_id', afterId);
    const body = await getJson(`${base}/v1/models?${query.toString()}`, headers, 'Anthropic', deps);
    const data = Array.isArray(body.data) ? body.data : [];
    for (const item of data) {
      const parsed = parseAnthropicModel(item);
      if (parsed) out.push(parsed);
    }
    const lastId = str(body.last_id);
    if (body.has_more === true && lastId && lastId !== afterId) afterId = lastId;
    else break;
  }
  return out;
}

/* ─── OpenAI ────────────────────────────────────────────────── */

/** `shutdown_date` may be a date string or a unix timestamp. */
export function parseShutdownDate(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return new Date(value * 1000).toISOString();
  }
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const text = value.trim();
  const ms = /^\d+$/.test(text) ? Number(text) * 1000 : Date.parse(text);
  return Number.isFinite(ms) ? new Date(ms).toISOString() : undefined;
}

/** Organization and project ids are short identifiers (`org-...`, `proj_...`). */
const SCOPE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

/** True when `value` is safe to send as an `OpenAI-Organization` or `OpenAI-Project` header. */
export function isValidScopeId(value: string): boolean {
  return SCOPE_ID.test(value);
}

export async function fetchOpenAiModels(creds: ProviderCreds, deps: LiveFetchDeps = {}): Promise<LiveModel[]> {
  const key = requireKey(creds, 'OpenAI');
  const base = await assertSafeBaseUrl(creds.baseUrl?.trim() || OPENAI_DEFAULT_BASE, deps);
  const headers: Record<string, string> = { Authorization: `Bearer ${key}`, Accept: 'application/json' };
  // A value that is not an identifier is not sent.
  const organization = creds.organization?.trim();
  const project = creds.project?.trim();
  if (organization && isValidScopeId(organization)) headers['OpenAI-Organization'] = organization;
  if (project && isValidScopeId(project)) headers['OpenAI-Project'] = project;
  const body = await getJson(`${base}/models`, headers, 'OpenAI', deps);
  const out: LiveModel[] = [];
  for (const item of Array.isArray(body.data) ? body.data : []) {
    if (!isObject(item)) continue;
    const id = str(item.id);
    if (!id) continue;
    const model: LiveModel = { id };
    const retiresAt = parseShutdownDate(item.shutdown_date);
    if (retiresAt) model.retiresAt = retiresAt;
    out.push(model);
  }
  return out;
}

/* ─── Gemini API ────────────────────────────────────────────── */

export async function fetchGeminiApiModels(creds: ProviderCreds, deps: LiveFetchDeps = {}): Promise<LiveModel[]> {
  const key = requireKey(creds, 'Gemini API');
  const base = await assertSafeBaseUrl(GEMINI_API_LIST_BASE, deps);
  // The key goes in a header, never the query string, so no URL carries it.
  const headers = { 'x-goog-api-key': key, Accept: 'application/json' };
  const out: LiveModel[] = [];
  let pageToken: string | undefined;
  for (let page = 0; page < MAX_PAGES; page++) {
    const query = new URLSearchParams({ pageSize: '1000' });
    if (pageToken) query.set('pageToken', pageToken);
    const body = await getJson(`${base}/models?${query.toString()}`, headers, 'Gemini API', deps);
    for (const item of Array.isArray(body.models) ? body.models : []) {
      if (!isObject(item)) continue;
      const name = str(item.name);
      if (!name) continue;
      const model: LiveModel = { id: name.replace(/^models\//, '') };
      const displayName = str(item.displayName);
      if (displayName) model.displayName = displayName;
      const ctx = posInt(item.inputTokenLimit);
      if (ctx) model.contextWindow = ctx;
      const maxOut = posInt(item.outputTokenLimit);
      if (maxOut) model.maxOutput = maxOut;
      out.push(model);
    }
    const next = str(body.nextPageToken);
    if (next && next !== pageToken) pageToken = next;
    else break;
  }
  return out;
}

/* ─── Dispatch ──────────────────────────────────────────────── */

/**
 * The provider's live list, or null when the provider has none to fetch
 * (Vertex without a Gemini API key).
 */
export async function fetchLiveModels(
  provider: ProviderId,
  creds: ProviderCreds,
  deps: LiveFetchDeps = {},
): Promise<LiveModel[] | null> {
  switch (provider) {
    case 'anthropic':
      return await fetchAnthropicModels(creds, deps);
    case 'openai':
      return await fetchOpenAiModels(creds, deps);
    case 'vertex':
      return creds.apiKey?.trim() ? await fetchGeminiApiModels(creds, deps) : null;
  }
}
