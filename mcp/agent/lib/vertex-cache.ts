/**
 * Vertex AI context-cache helper.
 *
 * Vertex's `cachedContents` API lets you upload
 * a chunk of context once and reference it by name on subsequent
 * `generateContent` calls. Cached input tokens are billed at ~25% of
 * the regular rate, so for a system prompt that ships identically
 * across thousands of turns the savings are real.
 *
 * Phantom's stable system prompt (see
 * `lib/system-prompt.ts`) is ~13k tokens. With `gemini-2.5-flash`'s
 * 1024-token cache minimum, this is well above the floor; with
 * a Pro model's 32k minimum (sometimes; varies by region and
 * version), it's below — the create call fails. This module handles
 * both gracefully: try create, fall back to no-cache on failure.
 *
 * Architecture:
 *
 *   - In-process Map keyed by `${model}:${sha256-of-systemPromptText}`.
 *     The hash key means action-policy changes (which mutate the
 *     prompt) automatically force a fresh cache; matching prompts
 *     reuse.
 *   - Each entry stores the Vertex cache resource name + the
 *     local-clock expiry (computed from the requested TTL).
 *   - Lookups return a cache name if non-expired, or null if missing
 *     / expired / previously-failed.
 *   - Failures are sticky for `FAILURE_BACKOFF_MS` (5min) so we
 *     don't hammer Vertex with create requests for prompts that
 *     don't qualify (e.g., below size minimum).
 *
 * Thread-safety: this is an in-memory Map mutated from request
 * handlers. Next.js runs request handlers in the same Node process;
 * concurrent reads/writes to a Map are safe in single-threaded JS,
 * but DOUBLE-CREATES (two requests racing to create the same cache)
 * are possible and benign — one cache wins, the other becomes a 1h
 * orphan that's auto-cleaned by Vertex on its TTL.
 *
 * Caller integration: see app/api/chat/route.ts callGeminiWithVertex
 * for the wiring. The pattern is:
 *
 *     const cacheName = await getOrCreateSystemPromptCache(...);
 *     const requestBody = cacheName
 *       ? { ...payload, cachedContent: cacheName, systemInstruction: undefined }
 *       : payload;
 *
 * Vertex requires that when `cachedContent` is set, the request must
 * NOT also include the same systemInstruction inline — that's
 * redundant and the API rejects it.
 */

import { createHash } from 'node:crypto';

const VERTEX_API_BASE = 'https://aiplatform.googleapis.com/v1';

/** Cache TTL requested from Vertex on create. 1h is generous for the
 *  per-process amortization horizon — most chat sessions complete or
 *  pause well within an hour. The cache is auto-cleaned by Vertex
 *  past TTL; we proactively refresh inside our local-clock cutoff. */
const CACHE_TTL_SECONDS = 3600;

/** Refresh the local-cache entry this many seconds BEFORE the
 *  upstream TTL expires, to avoid a request landing on a freshly-
 *  expired Vertex resource. */
const PROACTIVE_REFRESH_BUFFER_SECONDS = 60;

/** When a create call fails (size minimum, unsupported model, auth
 *  blip), suppress retries for this long so we don't waste API calls.
 *  The next request after this window will retry once. */
const FAILURE_BACKOFF_MS = 5 * 60 * 1000;

interface CacheEntry {
  /** Vertex cache resource name, e.g.
   *  `projects/.../locations/.../cachedContents/abc`. Null if create
   *  failed (sticky for FAILURE_BACKOFF_MS — see `failedAt`). */
  name: string | null;
  /** Local-clock epoch ms when this entry should be considered
   *  stale and re-created. */
  expiresAt: number;
  /** If `name` is null, the wall-clock ms when the failure happened.
   *  Used to honor FAILURE_BACKOFF_MS without blocking forever. */
  failedAt?: number;
}

const cache = new Map<string, CacheEntry>();

function hashSystemPrompt(text: string): string {
  return createHash('sha256').update(text).digest('hex').slice(0, 16);
}

/**
 * Get a Vertex cache resource for `systemPromptText`, creating one
 * if needed.
 *
 * Returns the resource name on success, or null when:
 *   - The create call fails (size minimum, unsupported model, etc).
 *     Failures are sticky for FAILURE_BACKOFF_MS so we don't hammer.
 *   - Network blip during create (also sticky-failed for backoff).
 *
 * Callers must handle null by falling back to inline systemInstruction.
 */
export async function getOrCreateSystemPromptCache(args: {
  systemPromptText: string;
  modelName: string;
  projectId: string;
  location: string;
  accessToken: string;
}): Promise<string | null> {
  const { systemPromptText, modelName, projectId, location, accessToken } = args;
  if (!systemPromptText) return null;

  const key = `${modelName}:${hashSystemPrompt(systemPromptText)}`;
  const now = Date.now();
  const existing = cache.get(key);

  if (existing) {
    // Sticky-failed entries: respect the backoff window.
    if (existing.name === null && existing.failedAt) {
      if (now - existing.failedAt < FAILURE_BACKOFF_MS) return null;
      // Backoff elapsed — fall through and try again.
    } else if (existing.name && existing.expiresAt > now) {
      return existing.name;
    }
  }

  // Create a fresh cached content. Vertex's API expects the model in
  // its full path form: `projects/.../locations/.../publishers/google/models/<id>`.
  const fullModelPath =
    `projects/${projectId}/locations/${location}/publishers/google/models/${modelName}`;
  let response: Response;
  try {
    response = await fetch(
      `${VERTEX_API_BASE}/projects/${encodeURIComponent(projectId)}/locations/${encodeURIComponent(location)}/cachedContents`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: fullModelPath,
          systemInstruction: {
            role: 'system',
            parts: [{ text: systemPromptText }],
          },
          ttl: `${CACHE_TTL_SECONDS}s`,
        }),
      },
    );
  } catch (err) {
    cache.set(key, { name: null, expiresAt: now + FAILURE_BACKOFF_MS, failedAt: now });
    console.warn(
      'vertex-cache: network error creating cache:',
      err instanceof Error ? err.message : err,
    );
    return null;
  }

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    cache.set(key, { name: null, expiresAt: now + FAILURE_BACKOFF_MS, failedAt: now });
    // Don't log at error level — most failures are expected (size
    // minimum). Stay at warn so it's visible but not alarming.
    console.warn(
      `vertex-cache: create failed (${response.status}); falling back to inline systemInstruction:`,
      text.slice(0, 200),
    );
    return null;
  }

  let data: { name?: string };
  try {
    data = (await response.json()) as { name?: string };
  } catch {
    cache.set(key, { name: null, expiresAt: now + FAILURE_BACKOFF_MS, failedAt: now });
    return null;
  }
  if (!data.name) {
    cache.set(key, { name: null, expiresAt: now + FAILURE_BACKOFF_MS, failedAt: now });
    return null;
  }

  // Success. Local-clock expiry is upstream TTL minus the proactive
  // refresh buffer so we never reference a just-expired Vertex
  // resource.
  cache.set(key, {
    name: data.name,
    expiresAt: now + (CACHE_TTL_SECONDS - PROACTIVE_REFRESH_BUFFER_SECONDS) * 1000,
  });
  return data.name;
}

/**
 * Test/debug-only: clear the in-process cache. Useful for unit tests
 * and for "force a fresh create" workflows. Not exposed to operator
 * traffic.
 */
export function _resetVertexCacheForTest(): void {
  cache.clear();
}
