/**
 * Anthropic API errors -> `ProviderError`.
 *
 * One mapping serves both the HTTP error response and the in-stream `error`
 * event, because they share a body: `{type: "error", error: {type, message,
 * details?}, request_id?}`.
 *
 * What is retryable (the transport retries up to 3 times):
 *   429 rate limit (honouring `retry-after`), 500 `api_error`, 503, 504
 *   `timeout_error`, 529 `overloaded_error`, other 5xx, and a dropped stream.
 *
 * What is never retried, because waiting cannot help:
 *   - the tier's monthly spend cap: a 429 whose `details.error_code` is
 *     `enforced_spend_limit_reached`, with no `retry-after`;
 *   - the operator's own usage limit: a 400 starting "You have reached your
 *     specified API usage limits";
 *   - `billing_error` (402), authentication, permission, invalid requests.
 *
 * Error text reflects only the JSON `error.message` (redacted by
 * `ProviderError`); a body that is not JSON is never echoed.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { ProviderError } from '../errors.ts';
import type { ProviderErrorKind } from '../types.ts';

export interface AnthropicErrorInput {
  /** HTTP status; absent for an in-stream error event. */
  status?: number;
  /** The parsed body (or event payload); anything else is treated as empty. */
  body: unknown;
  retryAfterMs?: number;
  /** From the `request-id` response header. */
  requestId?: string;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const SPEND_LIMIT_MESSAGE = /reached your specified api usage limits/i;
const SPEND_CAP_CODE = 'enforced_spend_limit_reached';
const CONTEXT_MESSAGE =
  /prompt is too long|exceed(?:s|ed)? (?:the )?(?:model'?s? )?context (?:window|limit|length)|context (?:window|length|limit) (?:exceeded|of)|too many (?:input )?tokens|input length and `?max_tokens`? exceed/i;

/** True when the failure is a spend cap or usage limit: waiting will not clear it. */
export function isSpendLimit(status: number | undefined, type: string | undefined, message: string, code: string | undefined): boolean {
  if (code === SPEND_CAP_CODE) return true;
  if (SPEND_LIMIT_MESSAGE.test(message)) return true;
  return status === 402 || type === 'billing_error';
}

export function providerErrorFromApi(input: AnthropicErrorInput): ProviderError {
  const body = isObject(input.body) ? input.body : {};
  const error = isObject(body.error) ? body.error : {};
  const type = typeof error.type === 'string' ? error.type : undefined;
  const rawMessage = typeof error.message === 'string' && error.message ? error.message : '';
  const details = isObject(error.details) ? error.details : {};
  const code = typeof details.error_code === 'string' ? details.error_code : undefined;
  const requestId = input.requestId ?? (typeof body.request_id === 'string' ? body.request_id : undefined);
  const status = input.status;

  let kind: ProviderErrorKind;
  let retryable = false;
  if (isSpendLimit(status, type, rawMessage, code)) {
    kind = 'quota_exhausted';
  } else if (status === 429 || type === 'rate_limit_error') {
    kind = 'rate_limit';
    retryable = true;
  } else if (status === 529 || type === 'overloaded_error') {
    kind = 'overloaded';
    retryable = true;
  } else if (status === 401 || type === 'authentication_error') {
    kind = 'auth';
  } else if (status === 403 || type === 'permission_error') {
    kind = 'permission';
  } else if (status === 404 || type === 'not_found_error') {
    kind = 'model_not_found';
  } else if (status === 413 || type === 'request_too_large') {
    kind = 'invalid_request';
  } else if (
    (status !== undefined && status >= 500) ||
    type === 'api_error' ||
    type === 'timeout_error'
  ) {
    kind = 'unavailable';
    retryable = true;
  } else if (CONTEXT_MESSAGE.test(rawMessage)) {
    kind = 'context_exceeded';
  } else if (status === 400 || type === 'invalid_request_error') {
    kind = 'invalid_request';
  } else {
    kind = 'unknown';
  }
  // A context overflow arrives as a 400 invalid_request_error.
  if (kind === 'invalid_request' && CONTEXT_MESSAGE.test(rawMessage)) kind = 'context_exceeded';

  const where = status !== undefined ? `HTTP ${status}${type ? `, ${type}` : ''}` : type ?? 'stream error';
  const text = rawMessage || 'no detail was given';
  const suffix = requestId ? ` [request ${requestId}]` : '';
  return new ProviderError({
    kind,
    message: `Anthropic API error (${where}): ${text}${suffix}`,
    retryable,
    retryAfterMs: input.retryAfterMs,
    status,
    requestId,
  });
}

export { parseRetryAfter, streamBrokenError } from '../streaming-call.ts';
