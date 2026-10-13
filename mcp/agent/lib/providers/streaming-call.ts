/**
 * One streamed HTTPS call to a model provider, with the timers and retry
 * policy every streaming adapter shares (the Claude and OpenAI transports sit
 * on top of this; each supplies its own URL, headers, error mapping and stream
 * reader).
 *
 * Timing: a 120 s idle timer that any network chunk resets (keep-alive pings
 * included), and an overall deadline for the whole call. `guardedFetch` also
 * carries a hard timeout, set just past the deadline, because its default
 * would abort the body of a long stream. A caller abort, the deadline and the
 * idle timer each produce their own error; only the idle one is retryable.
 *
 * Retry: up to 3 retries with backoff for errors the vendor's mapping marks
 * retryable. A retry is a fresh request, safe because nothing is handed on
 * until the stream has been read to its end. Never retried: a caller abort,
 * the deadline, and a `retry-after` that is longer than a minute or would
 * outlast the deadline.
 *
 * The URL has already passed the outbound-URL guard; `guardedFetch` refuses
 * redirects, so a credential in the headers is never forwarded.
 *
 * Error text never carries a key, a URL or a response body.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { abortedError, ProviderError } from './errors.ts';
import { withProviderRetry, type RetryClassification, type RetryHooks, type RetryPolicy } from './retry.ts';
import { guardedFetch } from './url-guard.ts';

export const IDLE_TIMEOUT_MS = 120_000;
export const DEADLINE_MS = 15 * 60_000;
export const MAX_RETRIES = 3;
/** A longer `retry-after` is surfaced to the caller instead of slept through. */
export const MAX_RETRY_AFTER_MS = 60_000;

export interface StreamingDeps {
  /** Defaults to the global `fetch`, looked up at call time. */
  fetch?: typeof fetch;
  idleTimeoutMs?: number;
  deadlineMs?: number;
  retry?: RetryHooks;
  now?: () => number;
}

export interface FailedResponse {
  status: number;
  /** The parsed JSON body; undefined when it was not JSON (never echoed). */
  body: unknown;
  retryAfterMs?: number;
  requestId?: string;
}

export interface StreamingRequest<T> {
  /** The vendor's name, for error text: "Anthropic". */
  vendor: string;
  url: string;
  headers: Record<string, string>;
  payload: string;
  /** Response headers that may carry the request id, first match wins. */
  requestIdHeaders: readonly string[];
  retryPolicy: RetryPolicy;
  /** Map a non-2xx answer to the vendor's error. */
  errorFromResponse(failed: FailedResponse): ProviderError;
  /** Read the event stream to its end. `onChunk` runs for every network chunk. */
  readStream(
    body: ReadableStream<Uint8Array>,
    opts: { onChunk: () => void; requestId?: string },
  ): Promise<T>;
}

/** `retry-after` header (seconds, or an HTTP date) -> milliseconds. */
export function parseRetryAfter(value: string | null | undefined, now: () => number = Date.now): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.round(seconds * 1000);
  const at = Date.parse(value);
  if (Number.isFinite(at)) return Math.max(0, at - now());
  return undefined;
}

/** The stream ended, or sent something unreadable, before the answer was complete. */
export function streamBrokenError(message: string): ProviderError {
  return new ProviderError({ kind: 'network', message, retryable: true });
}

async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    // A body that is not JSON is never echoed.
    return undefined;
  }
}

const aborted = abortedError;

function deadlineExceeded(vendor: string, deadlineMs: number): ProviderError {
  return new ProviderError({
    kind: 'network',
    code: 'DEADLINE_EXCEEDED',
    message: `The ${vendor} request did not finish within ${Math.round(deadlineMs / 1000)} s.`,
  });
}

/**
 * Turn whatever the attempt threw into a `ProviderError`, deciding from our own
 * flags why a request was aborted (the abort itself carries no reason that
 * `guardedFetch` preserves).
 */
function interpretFailure(
  err: unknown,
  vendor: string,
  state: { callerAborted: boolean; idleHit: boolean; deadlineHit: boolean; idleMs: number; deadlineMs: number },
): ProviderError {
  if (state.callerAborted) return aborted();
  if (state.deadlineHit) return deadlineExceeded(vendor, state.deadlineMs);
  if (state.idleHit) {
    return new ProviderError({
      kind: 'network',
      code: 'IDLE_TIMEOUT',
      message: `The ${vendor} stream sent nothing for ${Math.round(state.idleMs / 1000)} s.`,
      retryable: true,
    });
  }
  if (err instanceof ProviderError) return err;
  return new ProviderError({
    kind: 'network',
    message: `The ${vendor} stream was interrupted.`,
    retryable: true,
    cause: err,
  });
}

/** `retry-after-ms` (milliseconds) wins over `retry-after` when a vendor sends both. */
function retryAfterFrom(headers: Headers, now: () => number): number | undefined {
  const ms = Number(headers.get('retry-after-ms'));
  if (headers.get('retry-after-ms') !== null && Number.isFinite(ms) && ms >= 0) return Math.round(ms);
  return parseRetryAfter(headers.get('retry-after'), now);
}

export async function callStreaming<T>(
  spec: StreamingRequest<T>,
  deps: StreamingDeps = {},
  callerSignal?: AbortSignal,
): Promise<{ value: T; requestId?: string }> {
  const now = deps.now ?? Date.now;
  const idleMs = deps.idleTimeoutMs ?? IDLE_TIMEOUT_MS;
  const deadlineMs = deps.deadlineMs ?? DEADLINE_MS;
  const deadlineAt = now() + deadlineMs;

  async function attempt(): Promise<{ value: T; requestId?: string }> {
    if (callerSignal?.aborted) throw aborted();
    const remaining = deadlineAt - now();
    if (remaining <= 0) throw deadlineExceeded(spec.vendor, deadlineMs);

    const controller = new AbortController();
    let idleHit = false;
    let deadlineHit = false;
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    const resetIdle = (): void => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        idleHit = true;
        controller.abort();
      }, idleMs);
    };
    const deadlineTimer = setTimeout(() => {
      deadlineHit = true;
      controller.abort();
    }, remaining);
    const onCallerAbort = (): void => controller.abort();
    callerSignal?.addEventListener('abort', onCallerAbort, { once: true });
    resetIdle();

    try {
      const response = await guardedFetch(
        spec.url,
        { method: 'POST', headers: spec.headers, body: spec.payload },
        { fetch: deps.fetch, timeoutMs: remaining + 5000, signal: controller.signal },
      );
      let requestId: string | undefined;
      for (const name of spec.requestIdHeaders) {
        const value = response.headers.get(name);
        if (value) {
          requestId = value;
          break;
        }
      }
      if (!response.ok) {
        throw spec.errorFromResponse({
          status: response.status,
          body: await readErrorBody(response),
          retryAfterMs: retryAfterFrom(response.headers, now),
          requestId,
        });
      }
      if (!(response.headers.get('content-type') ?? '').includes('text/event-stream') || !response.body) {
        throw new ProviderError({
          kind: 'unknown',
          message: `The ${spec.vendor} endpoint did not answer with an event stream.`,
          status: response.status,
          requestId,
        });
      }
      const value = await spec.readStream(response.body, { onChunk: resetIdle, requestId });
      return { value, requestId };
    } catch (err) {
      throw interpretFailure(err, spec.vendor, {
        callerAborted: callerSignal?.aborted === true,
        idleHit,
        deadlineHit,
        idleMs,
        deadlineMs,
      });
    } finally {
      if (idleTimer) clearTimeout(idleTimer);
      clearTimeout(deadlineTimer);
      callerSignal?.removeEventListener('abort', onCallerAbort);
    }
  }

  const classify = (err: unknown): RetryClassification => {
    if (!(err instanceof ProviderError) || !err.retryable || callerSignal?.aborted) return { retryable: false };
    const wait = err.retryAfterMs;
    if (wait !== undefined && (wait > MAX_RETRY_AFTER_MS || now() + wait >= deadlineAt)) {
      return { retryable: false };
    }
    return { retryable: true, retryAfterMs: wait };
  };

  return await withProviderRetry(attempt, classify, spec.retryPolicy, deps.retry);
}
