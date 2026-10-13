/**
 * "Does this Gemini model exist and is it enabled for these credentials?"
 *
 * Vertex has no usable model list, so the registry cannot prove a curated model
 * is enabled. This asks the provider directly with `:countTokens`, which
 * generates nothing and costs nothing: Vertex first when only a service
 * account exists; the Gemini API first when a key exists, falling back to
 * Vertex when the key is rejected and a service account is also configured
 * (the same order a chat turn uses).
 *
 * Reuses the transport's credential parsing, location rule and auth factory.
 * Error text reflects only a JSON `error.message`, redacted; URLs and bodies
 * are never echoed, because the Gemini key could ride in one.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { redactSecrets } from '../errors.ts';
import type { ProviderCreds } from '../types.ts';
import { guardedFetch } from '../url-guard.ts';
import {
  GEMINI_API_BASE,
  VERTEX_API_BASE,
  isInvalidGeminiApiKeyError,
  makeGeminiAuth,
  parseCredentialsInput,
  resolveVertexLocation,
  type GeminiTransportDeps,
} from './transport.ts';

export interface VerifyResult {
  ok: boolean;
  /** Which path answered. */
  via: 'gemini-api' | 'vertex' | null;
  message: string;
}

const PROBE = { contents: [{ role: 'user', parts: [{ text: 'ping' }] }] };

async function errorText(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && 'error' in body) {
      const error = (body as { error?: { message?: unknown } }).error;
      if (error && typeof error.message === 'string' && error.message) return `: ${error.message}`;
    }
  } catch {
    // Not JSON: nothing is echoed.
  }
  return '';
}

function describe(status: number, detail: string, model: string): string {
  if (status === 404) return `${model} was not found, or it is not enabled for these credentials${detail}`;
  if (status === 401 || status === 403) return `The credentials were rejected (HTTP ${status})${detail}`;
  if (status === 429) return `The provider is rate limiting this check (HTTP 429)${detail}`;
  return `The check failed (HTTP ${status})${detail}`;
}

async function viaGeminiApi(creds: ProviderCreds, model: string, deps: GeminiTransportDeps): Promise<Response> {
  return await guardedFetch(
    `${GEMINI_API_BASE}/models/${encodeURIComponent(model)}:countTokens`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': creds.apiKey ?? '' },
      body: JSON.stringify(PROBE),
    },
    { fetch: deps.fetch, timeoutMs: 10_000 },
  );
}

async function viaVertex(creds: ProviderCreds, model: string, deps: GeminiTransportDeps): Promise<Response> {
  const { credentials, keyFile } = parseCredentialsInput(creds.serviceAccountJson ?? '');
  const auth = makeGeminiAuth(
    {
      credentials: credentials || undefined,
      keyFile: keyFile || undefined,
      scopes: ['https://www.googleapis.com/auth/cloud-platform'],
    },
    deps,
  );
  const projectId = credentials?.project_id || (await auth.getProjectId());
  if (!projectId) throw new Error('Vertex AI needs a project_id in the service-account JSON.');
  const accessToken = await auth.getAccessToken();
  if (!accessToken) throw new Error('Could not obtain a Vertex AI access token.');
  const location = resolveVertexLocation(model);
  return await guardedFetch(
    `${VERTEX_API_BASE}/projects/${encodeURIComponent(projectId)}/locations/${location}` +
      `/publishers/google/models/${encodeURIComponent(model)}:countTokens`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify(PROBE),
    },
    { fetch: deps.fetch, timeoutMs: 10_000 },
  );
}

export async function verifyGeminiModel(
  creds: ProviderCreds,
  model: string,
  deps: GeminiTransportDeps = {},
): Promise<VerifyResult> {
  const hasKey = Boolean(creds.apiKey?.trim());
  const hasServiceAccount = Boolean(creds.serviceAccountJson?.trim());
  if (!hasKey && !hasServiceAccount) {
    return { ok: false, via: null, message: 'No Google credentials are configured. Add a Vertex AI or Gemini API provider on the Providers page.' };
  }
  try {
    let via: VerifyResult['via'] = hasKey ? 'gemini-api' : 'vertex';
    let response = hasKey ? await viaGeminiApi(creds, model, deps) : await viaVertex(creds, model, deps);
    if (!response.ok && hasKey && hasServiceAccount) {
      const detail = await errorText(response.clone());
      if (response.status === 400 && isInvalidGeminiApiKeyError(new Error(detail))) {
        via = 'vertex';
        response = await viaVertex(creds, model, deps);
      }
    }
    if (response.ok) {
      return { ok: true, via, message: `${model} answered a token count${via === 'vertex' ? ' on Vertex AI' : ' on the Gemini API'}.` };
    }
    return { ok: false, via, message: redactSecrets(describe(response.status, await errorText(response), model)) };
  } catch (err) {
    const text = err instanceof Error ? err.message : '';
    // A JSON syntax error quotes a snippet of the input, which here is a private key.
    const message = !text || /JSON parse failed/.test(text) ? 'The service-account JSON could not be read.' : text;
    return { ok: false, via: null, message: redactSecrets(message) };
  }
}
