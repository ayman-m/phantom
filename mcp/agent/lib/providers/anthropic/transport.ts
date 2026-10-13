/**
 * Anthropic Messages transport: one streamed `POST {base}/v1/messages`.
 *
 * Request: `Authorization: Bearer <key>` (the documented primary; `x-api-key`
 * is the legacy fallback), `anthropic-version: 2023-06-01`, and one
 * comma-joined `anthropic-beta` header only when the builder asked for betas.
 * The base URL is operator-set, so it goes through `assertSafeBaseUrl` on every
 * call (https only, no loopback, link-local or install-internal hosts, resolved
 * addresses re-checked) and the request through `guardedFetch` (redirects are
 * never followed, so the key cannot be forwarded).
 *
 * The timers (120 s idle, overall deadline) and the retry loop are the shared
 * `callStreaming`. What is retryable here: 429 honouring `retry-after`, 529,
 * 503, 5xx, a dropped or broken stream, a mid-stream `error` event. Never
 * retried: a spend cap or usage limit (see `errors.ts`).
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { ProviderError } from '../errors.ts';
import { ANTHROPIC_DEFAULT_BASE } from '../registry/live.ts';
import type { RetryPolicy } from '../retry.ts';
import { callStreaming, type StreamingDeps } from '../streaming-call.ts';
import type { ProviderCreds } from '../types.ts';
import { assertSafeBaseUrl, type HostResolver } from '../url-guard.ts';
import { providerErrorFromApi } from './errors.ts';
import { readAnthropicStream, type AssembledMessage } from './stream.ts';

export { DEADLINE_MS, IDLE_TIMEOUT_MS, MAX_RETRIES, MAX_RETRY_AFTER_MS } from '../streaming-call.ts';

export const ANTHROPIC_VERSION = '2023-06-01';

const RETRY_POLICY: RetryPolicy = {
  maxRetries: 3,
  initialDelayMs: 1000,
  backoffFactor: 2,
  jitterMs: 500,
  label: 'anthropic',
  reason: 'request failed with a retryable error',
};

export interface AnthropicTransportDeps extends StreamingDeps {
  /** Hosts to refuse beyond the built-in list, e.g. the MCP host. */
  blockedHosts?: readonly string[];
  /** Defaults to the system resolver. */
  resolveHost?: HostResolver;
}

export interface AnthropicCallResult {
  message: AssembledMessage;
  requestId?: string;
}

export function requestHeaders(apiKey: string, betas: readonly string[]): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    'anthropic-version': ANTHROPIC_VERSION,
    'content-type': 'application/json',
    accept: 'text/event-stream',
  };
  // Google Cloud reads a single anthropic-beta header; the API accepts the same form.
  if (betas.length > 0) headers['anthropic-beta'] = betas.join(',');
  return headers;
}

export async function callAnthropicMessages(
  body: Record<string, unknown>,
  betas: readonly string[],
  creds: ProviderCreds,
  deps: AnthropicTransportDeps = {},
  callerSignal?: AbortSignal,
): Promise<AnthropicCallResult> {
  const apiKey = creds.apiKey?.trim();
  if (!apiKey) {
    throw new ProviderError({
      kind: 'auth',
      code: 'PROVIDER_NOT_CONFIGURED',
      message: 'No Anthropic API key is configured. Add one on the Providers page, then try again.',
    });
  }
  const base = await assertSafeBaseUrl(creds.baseUrl?.trim() || ANTHROPIC_DEFAULT_BASE, {
    blockedHosts: deps.blockedHosts,
    resolveHost: deps.resolveHost,
  });
  const { value, requestId } = await callStreaming<AssembledMessage>(
    {
      vendor: 'Anthropic',
      url: `${base}/v1/messages`,
      headers: requestHeaders(apiKey, betas),
      payload: JSON.stringify(body),
      requestIdHeaders: ['request-id'],
      retryPolicy: RETRY_POLICY,
      errorFromResponse: (failed) =>
        providerErrorFromApi({
          status: failed.status,
          body: failed.body,
          retryAfterMs: failed.retryAfterMs,
          requestId: failed.requestId,
        }),
      readStream: (stream, opts) => readAnthropicStream(stream, opts),
    },
    deps,
    callerSignal,
  );
  return { message: value, requestId };
}
