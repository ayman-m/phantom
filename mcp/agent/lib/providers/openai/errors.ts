/**
 * OpenAI API errors -> `ProviderError`.
 *
 * One mapping serves the HTTP error response, the in-stream `error` event and
 * the `error` object of a `response.failed` event. The documented HTTP body is
 * `{error: {message, type, param, code}}`; the stream forms may arrive flat
 * (`{type: "error", code, message}`) or wrapped, so both are read. These shapes
 * come from the vendor's public guides and are not yet confirmed against live
 * traffic.
 *
 * What is retryable (the transport retries up to 3 times):
 *   408, 409, 429 rate limit (honouring `retry-after`), 500, 502, 503, 504,
 *   other 5xx, `server_error`, `rate_limit_exceeded`, and a dropped stream.
 *
 * What is never retried, because waiting cannot help:
 *   - exhausted credit or a spend limit: `insufficient_quota` (code or type,
 *     including on a 429), a hard billing limit, "exceeded your current
 *     quota", HTTP 402;
 *   - authentication, permission, unknown model, invalid or oversize requests,
 *     a context overflow.
 *
 * Error text reflects only the JSON `message` (redacted by `ProviderError`); a
 * body that is not JSON is never echoed.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { ProviderError } from '../errors.ts';
import type { ProviderErrorKind } from '../types.ts';

export interface OpenAiErrorInput {
  /** HTTP status; absent for an in-stream error. */
  status?: number;
  /** The parsed body (or event payload); anything else is treated as empty. */
  body: unknown;
  retryAfterMs?: number;
  /** From the `x-request-id` response header. */
  requestId?: string;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

const QUOTA_CODES = new Set(['insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active']);
const QUOTA_MESSAGE =
  /exceeded your current quota|insufficient[_ ]quota|billing hard limit|hard limit has been reached|(?:monthly|spend|spending|usage|budget) (?:limit|cap)(?: has been)? (?:reached|exceeded)|reached (?:its|your|the) (?:monthly|spend|spending|usage|budget)/i;
const CONTEXT_CODES = new Set(['context_length_exceeded']);
const CONTEXT_MESSAGE =
  /context[_ ](?:length|window)(?: exceeded)?|maximum context length|exceeds? the (?:context|token) limit|input is too long|too many (?:input )?tokens/i;

/** True when the failure is exhausted credit or a spend limit: waiting will not clear it. */
export function isQuotaFailure(
  status: number | undefined,
  type: string | undefined,
  code: string | undefined,
  message: string,
): boolean {
  if (code !== undefined && QUOTA_CODES.has(code)) return true;
  if (type !== undefined && QUOTA_CODES.has(type)) return true;
  if (QUOTA_MESSAGE.test(message)) return true;
  return status === 402;
}

/** The `{message, type, code}` triple, from a wrapped or a flat error object. */
function readErrorFields(body: unknown): { message: string; type?: string; code?: string } {
  const root = isObject(body) ? body : {};
  const inner = isObject(root.error) ? root.error : root;
  // A flat stream event names itself `type: "error"`; that is not an error type.
  const type = str(inner.type);
  return {
    message: str(inner.message) ?? '',
    type: type === 'error' ? undefined : type,
    code: str(inner.code),
  };
}

export function providerErrorFromApi(input: OpenAiErrorInput): ProviderError {
  const { message: rawMessage, type, code } = readErrorFields(input.body);
  const status = input.status;
  const requestId = input.requestId;

  let kind: ProviderErrorKind;
  let retryable = false;
  if (isQuotaFailure(status, type, code, rawMessage)) {
    kind = 'quota_exhausted';
  } else if (status === 429 || code === 'rate_limit_exceeded' || type === 'rate_limit_exceeded' || type === 'requests' || type === 'tokens') {
    kind = 'rate_limit';
    retryable = true;
  } else if (status === 401 || code === 'invalid_api_key' || type === 'authentication_error') {
    kind = 'auth';
  } else if (status === 403 || type === 'permission_error' || code === 'permission_denied') {
    kind = 'permission';
  } else if (status === 404 || code === 'model_not_found') {
    kind = 'model_not_found';
  } else if (status === 503) {
    kind = 'overloaded';
    retryable = true;
  } else if (
    status === 408 ||
    status === 409 ||
    (status !== undefined && status >= 500) ||
    code === 'server_error' ||
    type === 'server_error'
  ) {
    kind = 'unavailable';
    retryable = true;
  } else if ((code !== undefined && CONTEXT_CODES.has(code)) || CONTEXT_MESSAGE.test(rawMessage)) {
    kind = 'context_exceeded';
  } else if (status === 400 || status === 413 || status === 422 || type === 'invalid_request_error' || code === 'invalid_prompt') {
    kind = 'invalid_request';
  } else {
    kind = 'unknown';
  }

  const label = [status !== undefined ? `HTTP ${status}` : undefined, type ?? code].filter(Boolean).join(', ');
  const where = label || 'stream error';
  const text = rawMessage || 'no detail was given';
  const suffix = requestId ? ` [request ${requestId}]` : '';
  return new ProviderError({
    kind,
    message: `OpenAI API error (${where}): ${text}${suffix}`,
    retryable,
    retryAfterMs: input.retryAfterMs,
    status,
    requestId,
  });
}
