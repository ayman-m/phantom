/**
 * Provider errors and secret redaction.
 *
 * `ProviderError.message` always passes through `redactSecrets()`, so an
 * adapter error can reach the console, an SSE frame or an audit row without
 * carrying a credential. Request and response bodies are never attached.
 *
 * Erasable TypeScript only; the one import is type-only.
 */

import type { ProviderErrorKind } from './types.ts';

/**
 * Strip credential-shaped substrings from free text. Order matters: the more
 * specific key prefixes run before the generic ones.
 */
export function redactSecrets(input: string): string {
  return input
    .replace(/sk-ant-[A-Za-z0-9_-]{8,}/g, 'sk-ant-***')
    .replace(/sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}/g, 'sk-***')
    .replace(/AIza[0-9A-Za-z_-]{20,}/g, 'AIza***')
    .replace(/\b((?:api[_-]?)?key=)[^&\s"']+/gi, '$1***')
    .replace(/(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi, '$1***');
}

export interface ProviderErrorInit {
  kind: ProviderErrorKind;
  /** Stable machine code for dispatch-level failures, e.g. PROVIDER_NOT_CONFIGURED. */
  code?: string;
  message: string;
  retryable?: boolean;
  retryAfterMs?: number;
  status?: number;
  requestId?: string;
  cause?: unknown;
}

export class ProviderError extends Error {
  readonly kind: ProviderErrorKind;
  readonly code: string | undefined;
  readonly retryable: boolean;
  readonly retryAfterMs: number | undefined;
  readonly status: number | undefined;
  readonly requestId: string | undefined;

  constructor(init: ProviderErrorInit) {
    super(redactSecrets(init.message), init.cause === undefined ? undefined : { cause: init.cause });
    this.name = 'ProviderError';
    this.kind = init.kind;
    this.code = init.code;
    this.retryable = init.retryable ?? false;
    this.retryAfterMs = init.retryAfterMs;
    this.status = init.status;
    this.requestId = init.requestId;
  }
}

/** The stable code of an error thrown because the caller cancelled the call. */
export const ABORTED_CODE = 'ABORTED';

/** The error every adapter throws when the caller's abort signal fires. */
export function abortedError(): ProviderError {
  return new ProviderError({ kind: 'network', code: ABORTED_CODE, message: 'The model request was cancelled.' });
}

/**
 * True when `err` means the caller cancelled (the browser closed), not that the
 * provider failed: an adapter's ABORTED error, or the AbortError a raw `fetch`
 * rejects with. Callers end the turn quietly instead of reporting a failure.
 */
export function isAbortedError(err: unknown): boolean {
  if (err instanceof ProviderError) return err.code === ABORTED_CODE;
  return err instanceof Error && err.name === 'AbortError';
}
