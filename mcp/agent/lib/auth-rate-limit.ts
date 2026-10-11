/**
 * In-memory failure limiter for the password-checking auth routes.
 *
 * One implementation, two instances:
 *   - `loginLimiter`           guards POST /api/auth/login
 *   - `changePasswordLimiter`  guards POST /api/auth/change-password
 *
 * Why the second one exists: change-password verifies the CURRENT password,
 * so without a limit a stolen session cookie lets an attacker guess the
 * password through that endpoint at the hash's speed, bypassing the login
 * lockout entirely. Each limiter has its own map, so failing one route never
 * locks the other.
 *
 * Window: MAX_FAILURES wrong guesses inside WINDOW_MS lock that key for
 * LOCKOUT_MS. State lives in process memory and resets when the container
 * restarts (the audit events are the durable record).
 *
 * Reserve, then settle. The password check is asynchronous, so counting a
 * failure only AFTER it returns would let N parallel requests all pass the
 * gate before any of them is counted. `acquire` therefore checks the gate and
 * counts the attempt in one synchronous step, BEFORE the check starts; the
 * caller then `clear`s on success, or `refund`s when the attempt proved
 * nothing about the password (service outage, expired session).
 *
 * Keys. The source address is the LAST X-Forwarded-For entry: tls-proxy.js
 * appends the real socket address to whatever the client sent, so earlier
 * entries are attacker-controlled and the last one is not. Change-password is
 * additionally keyed on a hash of the session token, because a stolen cookie is
 * the threat it exists to stop. A request is allowed only when every one of its
 * keys is.
 *
 * Memory: expired entries are swept once the map passes PRUNE_AT, and the map
 * never holds more than MAX_ENTRIES keys (oldest dropped first).
 *
 * Erasable-syntax TypeScript only (no parameter properties, enums or
 * namespaces) so scripts/test-auth-rate-limit.mjs can import this file
 * directly with Node's type stripping.
 */

import type { NextRequest } from "next/server";

export const WINDOW_MS = 60_000;
export const MAX_FAILURES = 5;
export const LOCKOUT_MS = 60_000;
export const PRUNE_AT = 1_000;
export const MAX_ENTRIES = 10_000;

interface Entry {
  failureCount: number;
  windowResetAt: number;
  lockedUntilMs: number;
}

export type RateGate = { allowed: true } | { allowed: false; retryAfter: number };

export class FailureLimiter {
  private readonly entries = new Map<string, Entry>();
  private readonly windowMs: number;
  private readonly maxFailures: number;
  private readonly lockoutMs: number;

  constructor(windowMs: number, maxFailures: number, lockoutMs: number) {
    this.windowMs = windowMs;
    this.maxFailures = maxFailures;
    this.lockoutMs = lockoutMs;
  }

  /** Number of keys currently held (for tests and diagnostics). */
  get size(): number {
    return this.entries.size;
  }

  /** Is this key currently locked out? Read-only apart from dropping its own expired entry. */
  check(key: string, now: number = Date.now()): RateGate {
    const entry = this.entries.get(key);
    if (entry && entry.lockedUntilMs > now) {
      return { allowed: false, retryAfter: Math.ceil((entry.lockedUntilMs - now) / 1000) };
    }
    if (entry && entry.windowResetAt < now && entry.lockedUntilMs <= now) {
      this.entries.delete(key);
    }
    return { allowed: true };
  }

  recordFailure(key: string, now: number = Date.now()): void {
    let entry = this.entries.get(key);
    if (!entry || entry.windowResetAt < now) {
      entry = { failureCount: 0, windowResetAt: now + this.windowMs, lockedUntilMs: 0 };
    }
    entry.failureCount += 1;
    if (entry.failureCount >= this.maxFailures) {
      entry.lockedUntilMs = now + this.lockoutMs;
    }
    // Re-insert so the Map's insertion order tracks recency (oldest first).
    this.entries.delete(key);
    this.entries.set(key, entry);
    this.bound(now);
  }

  /** Give back one reserved attempt that proved nothing about the password. */
  refund(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    entry.failureCount = Math.max(0, entry.failureCount - 1);
    if (entry.failureCount === 0) {
      this.entries.delete(key);
    } else if (entry.failureCount < this.maxFailures) {
      entry.lockedUntilMs = 0;
    }
  }

  clear(key: string): void {
    this.entries.delete(key);
  }

  private bound(now: number): void {
    if (this.entries.size <= PRUNE_AT) return;
    for (const [k, e] of this.entries) {
      if (e.windowResetAt < now && e.lockedUntilMs <= now) this.entries.delete(k);
    }
    // Still too many live keys: drop the oldest until under the cap.
    while (this.entries.size > MAX_ENTRIES) {
      const oldest = this.entries.keys().next();
      if (oldest.done) break;
      this.entries.delete(oldest.value);
    }
  }
}

export const loginLimiter = new FailureLimiter(WINDOW_MS, MAX_FAILURES, LOCKOUT_MS);
export const changePasswordLimiter = new FailureLimiter(WINDOW_MS, MAX_FAILURES, LOCKOUT_MS);

/** Read-only gate over several keys: the longest remaining lock wins. */
export function checkAll(limiter: FailureLimiter, keys: string[], now: number = Date.now()): RateGate {
  let retryAfter = 0;
  for (const key of keys) {
    const gate = limiter.check(key, now);
    if (!gate.allowed) retryAfter = Math.max(retryAfter, gate.retryAfter);
  }
  return retryAfter > 0 ? { allowed: false, retryAfter } : { allowed: true };
}

/**
 * Check every key and, only if all are open, count one attempt on each, in a
 * single synchronous step (no await between the check and the count).
 */
export function acquireAll(limiter: FailureLimiter, keys: string[], now: number = Date.now()): RateGate {
  const gate = checkAll(limiter, keys, now);
  if (!gate.allowed) return gate;
  for (const key of keys) limiter.recordFailure(key, now);
  return { allowed: true };
}

export function refundAll(limiter: FailureLimiter, keys: string[]): void {
  for (const key of keys) limiter.refund(key);
}

export function clearAll(limiter: FailureLimiter, keys: string[]): void {
  for (const key of keys) limiter.clear(key);
}

/**
 * The caller's address: the LAST X-Forwarded-For entry (see "Keys" above).
 * "unknown" covers the dev-loopback case where no header is present.
 */
export function getSourceIp(request: NextRequest): string {
  const xff = request.headers.get("x-forwarded-for");
  if (xff) {
    const parts = xff.split(",").map((p) => p.trim()).filter(Boolean);
    const last = parts[parts.length - 1];
    if (last) return last;
  }
  return request.headers.get("x-real-ip") || "unknown";
}

/** The 429 body shared by both routes. */
export function lockedResponseBody(retryAfter: number): { error: string; retryAfter: number } {
  return { error: `Too many failed attempts. Try again in ${retryAfter}s.`, retryAfter };
}
