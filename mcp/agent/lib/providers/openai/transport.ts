/**
 * OpenAI Responses transport: one streamed `POST {base}/responses`.
 *
 * Request: `Authorization: Bearer <key>`, `Content-Type: application/json`,
 * `Accept: text/event-stream`, and the optional `OpenAI-Organization` and
 * `OpenAI-Project` headers when the stored instance carries them. The base URL
 * is operator-set and already includes the version segment (the default is
 * `https://api.openai.com/v1`); it goes through `assertSafeBaseUrl` on every
 * call (https only, no loopback, link-local or install-internal hosts,
 * resolved addresses re-checked) and the request through `guardedFetch`
 * (redirects are never followed, so the key cannot be forwarded).
 *
 * The timers (120 s idle, overall deadline) and the retry loop are the shared
 * `callStreaming`. What is retryable here: 408, 409, 429 honouring
 * `retry-after`, 5xx, a dropped or broken stream, a retryable mid-stream error.
 * Never retried: exhausted credit or a spend limit, including a 429 that
 * carries `insufficient_quota` (see `errors.ts`).
 *
 * The request id is the `x-request-id` response header.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { ProviderError } from '../errors.ts';
import { isValidScopeId, OPENAI_DEFAULT_BASE } from '../registry/live.ts';
import type { RetryPolicy } from '../retry.ts';
import { callStreaming, type StreamingDeps } from '../streaming-call.ts';
import type { ProviderCreds } from '../types.ts';
import { assertSafeBaseUrl, type HostResolver } from '../url-guard.ts';
import { providerErrorFromApi } from './errors.ts';
import { readOpenAiStream, type AssembledResponse } from './stream.ts';

const RETRY_POLICY: RetryPolicy = {
  maxRetries: 3,
  initialDelayMs: 1000,
  backoffFactor: 2,
  jitterMs: 500,
  label: 'openai',
  reason: 'request failed with a retryable error',
};

export interface OpenAiTransportDeps extends StreamingDeps {
  /** Hosts to refuse beyond the built-in list, e.g. the MCP host. */
  blockedHosts?: readonly string[];
  /** Defaults to the system resolver. */
  resolveHost?: HostResolver;
}

export interface OpenAiCallResult {
  response: AssembledResponse;
  requestId?: string;
}

export function requestHeaders(creds: { apiKey: string; organization?: string; project?: string }): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${creds.apiKey}`,
    'content-type': 'application/json',
    accept: 'text/event-stream',
  };
  const organization = creds.organization?.trim();
  const project = creds.project?.trim();
  // A value that is not an identifier is not sent: a header value is never
  // built from free text.
  if (organization && isValidScopeId(organization)) headers['OpenAI-Organization'] = organization;
  if (project && isValidScopeId(project)) headers['OpenAI-Project'] = project;
  return headers;
}

export async function callOpenAiResponses(
  body: Record<string, unknown>,
  creds: ProviderCreds,
  deps: OpenAiTransportDeps = {},
  callerSignal?: AbortSignal,
): Promise<OpenAiCallResult> {
  const apiKey = creds.apiKey?.trim();
  if (!apiKey) {
    throw new ProviderError({
      kind: 'auth',
      code: 'PROVIDER_NOT_CONFIGURED',
      message: 'No OpenAI API key is configured. Add one on the Providers page, then try again.',
    });
  }
  const base = await assertSafeBaseUrl(creds.baseUrl?.trim() || OPENAI_DEFAULT_BASE, {
    blockedHosts: deps.blockedHosts,
    resolveHost: deps.resolveHost,
  });
  const { value, requestId } = await callStreaming<AssembledResponse>(
    {
      vendor: 'OpenAI',
      url: `${base}/responses`,
      headers: requestHeaders({ apiKey, organization: creds.organization, project: creds.project }),
      payload: JSON.stringify(body),
      requestIdHeaders: ['x-request-id'],
      retryPolicy: RETRY_POLICY,
      errorFromResponse: (failed) =>
        providerErrorFromApi({
          status: failed.status,
          body: failed.body,
          retryAfterMs: failed.retryAfterMs,
          requestId: failed.requestId,
        }),
      readStream: (stream, opts) => readOpenAiStream(stream, opts),
    },
    deps,
    callerSignal,
  );
  return { response: value, requestId };
}
