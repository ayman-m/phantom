/**
 * Retry policy shared by every provider adapter.
 *
 * `withProviderRetry` runs `fn`, asks `classify` whether a failure is worth
 * another attempt, and sleeps with exponential backoff plus jitter between
 * attempts. The Gemini policy below reproduces the previous
 * `withRateLimitRetry` exactly: same match strings (429 / RESOURCE_EXHAUSTED /
 * Resource exhausted / "rate limit"), 5 retries, 2 s base, x2 backoff, 0-1 s
 * jitter, same log line.
 *
 * Sleep, random and warn are injectable so tests do not wait real seconds.
 * Erasable TypeScript only; no imports.
 */

export interface RetryClassification {
  retryable: boolean;
  /** A server-provided wait (Retry-After). Used instead of the backoff step when larger. */
  retryAfterMs?: number;
}

export interface RetryPolicy {
  maxRetries: number;
  initialDelayMs: number;
  backoffFactor: number;
  /** Upper bound (exclusive) of the random jitter added to each wait. */
  jitterMs: number;
  label: string;
  /** Text that follows the label in the warn line, e.g. "hit 429". */
  reason: string;
}

export interface RetryHooks {
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  warn?: (message: string) => void;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export async function withProviderRetry<T>(
  fn: () => Promise<T>,
  classify: (err: unknown) => RetryClassification,
  policy: RetryPolicy,
  hooks: RetryHooks = {},
): Promise<T> {
  const sleep = hooks.sleep ?? defaultSleep;
  const random = hooks.random ?? Math.random;
  const warn =
    hooks.warn ??
    ((message: string) => {
      // eslint-disable-next-line no-console
      console.warn(message);
    });
  let delayMs = policy.initialDelayMs;
  let attempt = 0;
  while (true) {
    try {
      return await fn();
    } catch (err) {
      const verdict = classify(err);
      if (!verdict.retryable || attempt >= policy.maxRetries) {
        throw err;
      }
      attempt += 1;
      const jitterMs = Math.floor(random() * policy.jitterMs);
      const backoffMs = delayMs + jitterMs;
      const sleepMs =
        verdict.retryAfterMs !== undefined && verdict.retryAfterMs > backoffMs
          ? verdict.retryAfterMs
          : backoffMs;
      warn(
        `[chat] ${policy.label} ${policy.reason}; retry ${attempt}/${policy.maxRetries} in ${sleepMs}ms`,
      );
      await sleep(sleepMs);
      delayMs *= policy.backoffFactor;
    }
  }
}

/* ─── Gemini policy ─────────────────────────────────────────── */

/** True for the quota / rate-limit failures Vertex and the Gemini API return. */
export function classifyGeminiRateLimit(err: unknown): RetryClassification {
  const msg = err instanceof Error ? err.message : String(err);
  const isRateLimit =
    msg.includes('429') ||
    msg.includes('RESOURCE_EXHAUSTED') ||
    msg.includes('Resource exhausted') ||
    msg.toLowerCase().includes('rate limit');
  return { retryable: isRateLimit };
}

/**
 * Vertex/Gemini quota retry wrapper.
 *
 * Vertex projects hit per-minute quota under bursty agent load (several
 * 5-minute cron jobs overlapping with chat traffic). Without a retry, a 429 /
 * RESOURCE_EXHAUSTED would reach the operator as `Gemini API error: 429 ...`
 * and scheduled jobs as `chat error event: Vertex AI error: 429`. Only 429-class
 * errors retry; every other error propagates immediately so real bugs are not
 * masked.
 *
 * Pattern ported from our blackhat-noc Slack bot's `send_message_with_backoff`:
 * same shape, same numbers (initial 2 s, x2 each retry, 0-1 s jitter, max 5
 * retries).
 */
export function withRateLimitRetry<T>(
  fn: () => Promise<T>,
  opts: { maxRetries?: number; initialDelayMs?: number; label?: string } = {},
  hooks: RetryHooks = {},
): Promise<T> {
  return withProviderRetry(
    fn,
    classifyGeminiRateLimit,
    {
      maxRetries: opts.maxRetries ?? 5,
      initialDelayMs: opts.initialDelayMs ?? 2000,
      backoffFactor: 2,
      jitterMs: 1000,
      label: opts.label ?? 'gemini',
      reason: 'hit 429',
    },
    hooks,
  );
}
