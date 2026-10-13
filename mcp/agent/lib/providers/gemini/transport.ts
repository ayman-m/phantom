/**
 * Gemini transports: the Gemini Developer API (API key) and Vertex AI.
 *
 * Moved from the chat route with the logic untouched: `resolveVertexLocation`,
 * `detectPlaceholderCredential`, `parseCredentialsInput`,
 * `callGeminiWithApiKey`, `callGeminiWithVertex` and
 * `isInvalidGeminiApiKeyError`. The only changes are seams for tests: `fetch`,
 * the GoogleAuth factory, the system-prompt cache lookup and the retry sleeper
 * come in through `GeminiTransportDeps` and default to the real thing.
 * `callGeminiGenerateContent` is the API-key-first, Vertex-on-invalid-key
 * dispatch that the three route call sites each repeated.
 *
 * Never log URLs from here: the API-key path carries the key in the query.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { GoogleAuth, type GoogleAuthOptions } from 'google-auth-library';
import { getOrCreateSystemPromptCache } from '../../vertex-cache.ts';
import { withRateLimitRetry, type RetryHooks } from '../retry.ts';
import type { GeminiCallPayload } from './payload.ts';

export const GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta';
export const VERTEX_API_BASE = 'https://aiplatform.googleapis.com/v1';

/**
 * What each caller says when neither credential is configured. The wording
 * differs per entry point and is kept exactly as the chat route has always
 * worded it.
 */
export const GEMINI_NO_PROVIDER_MESSAGES = {
  chat:
    'No model provider is configured. Add a Vertex AI or Gemini API provider at /providers, then try again.',
  subagent:
    'No model provider is configured. Add a Vertex AI or Gemini API provider at /providers, then retry — the subagent uses the same provider as the main chat agent.',
  summarize:
    'No model provider is configured for the conversation summarizer. Add a Vertex AI or Gemini API provider at /providers.',
} as const;

/** The two credential fields the Gemini transports read. */
export interface GeminiCredentials {
  GEMINI_API_KEY?: string;
  GOOGLE_APPLICATION_CREDENTIALS?: string;
}

export interface GeminiAuthClient {
  getProjectId(): Promise<string | null | undefined>;
  getAccessToken(): Promise<string | null | undefined>;
}

export interface GeminiTransportDeps {
  /** Defaults to the global `fetch`, looked up at call time. */
  fetch?: typeof fetch;
  /** Defaults to `new GoogleAuth(opts)`. */
  createAuth?: (opts: {
    credentials?: unknown;
    keyFile?: string;
    scopes: string[];
  }) => GeminiAuthClient;
  /** Defaults to the Vertex context-cache helper. */
  getSystemPromptCache?: typeof getOrCreateSystemPromptCache;
  /** Defaults to `process.env.PHANTOM_VERTEX_CACHE === '1'`, read at call time. */
  vertexCacheEnabled?: () => boolean;
  /** Sleep / random / warn for the rate-limit retry. */
  retry?: RetryHooks;
  /** Cancels the in-flight request (and a retry about to start) when it fires. */
  signal?: AbortSignal;
}

/** The Google auth client for a service account or key file; injectable for tests. */
export function makeGeminiAuth(
  authOptions: { credentials?: unknown; keyFile?: string; scopes: string[] },
  deps: GeminiTransportDeps = {},
): GeminiAuthClient {
  return deps.createAuth
    ? deps.createAuth(authOptions)
    : new GoogleAuth(authOptions as GoogleAuthOptions);
}

function fetchOf(deps: GeminiTransportDeps): typeof fetch {
  return deps.fetch ?? ((input, init) => fetch(input, init));
}

/** The `signal` init field, only when a signal was given (keeps the request init unchanged otherwise). */
function signalInit(deps: GeminiTransportDeps): { signal?: AbortSignal } {
  return deps.signal ? { signal: deps.signal } : {};
}

export function resolveVertexLocation(modelName: string) {
  if (modelName.toLowerCase().includes('gemini-3') || modelName.toLowerCase().includes('experimental')) {
    return 'global';
  }
  return 'us-central1';
}

/**
 * Detect placeholder / sample / fake GCP service-account credentials.
 *
 * Without this guard, the GoogleAuth client downstream attempts a JWT
 * sign() on a fake `private_key`, Node's OpenSSL decoder throws
 * `error:1E08010C:DECODER routines::unsupported`, and that bubbles to
 * the operator as a cryptic Node error. Job runs in particular emit
 * a `job-run-failed` notification on every fire — noisy and unhelpful.
 *
 * We catch the obvious shapes pre-flight and turn the failure into a
 * clear operator-actionable message. The detection is intentionally
 * conservative — false positives would block legitimate operators with
 * unusual but valid keys, so we only flag patterns where the input
 * could not possibly authenticate.
 *
 * Returns a reason string when placeholder is detected, or null when
 * the credentials at least pass surface-level validity checks (a real
 * key could still fail at sign-time for other reasons; that's the auth
 * library's job to surface with its own errors).
 */
export function detectPlaceholderCredential(
  credentials: Record<string, unknown> | null,
): string | null {
  if (!credentials) return null;

  // Required structural fields that any real GCP service-account JSON has.
  // Missing any of these is a hard placeholder signal.
  const required = ['type', 'project_id', 'private_key', 'client_email'] as const;
  for (const field of required) {
    if (typeof credentials[field] !== 'string' || !(credentials[field] as string).trim()) {
      return `GOOGLE_APPLICATION_CREDENTIALS missing required field: ${field}`;
    }
  }

  const privateKey = String(credentials.private_key);
  // Real PKCS#8 RSA keys start with `-----BEGIN PRIVATE KEY-----` and
  // contain a base64 blob of ~1500-2000 chars. A real key body is at
  // least ~600 chars between the BEGIN/END markers (smaller P-256/P-384
  // keys aren't used by GCP service accounts as of writing).
  if (!privateKey.includes('BEGIN PRIVATE KEY') && !privateKey.includes('BEGIN RSA PRIVATE KEY')) {
    return 'GOOGLE_APPLICATION_CREDENTIALS private_key is not in PEM format';
  }
  // Strip the markers + newlines and check the base64 body length.
  const body = privateKey
    .replace(/-----BEGIN [A-Z ]+ KEY-----/g, '')
    .replace(/-----END [A-Z ]+ KEY-----/g, '')
    .replace(/[\r\n\\]/g, '')
    .trim();
  // Real GCP keys' base64 body is ~1600+ chars. Anything less is fake.
  // We also catch the literal string "fake" which is the most common
  // placeholder value in sample env files.
  if (body.length < 200 || /^fake$/i.test(body) || /^placeholder/i.test(body)) {
    return (
      'GOOGLE_APPLICATION_CREDENTIALS private_key looks like a placeholder ' +
      `(${body.length} chars between BEGIN/END markers; real keys are ~1600+ chars). ` +
      'Set GEMINI_API_KEY for direct API access, or replace with a real GCP service-account JSON.'
    );
  }
  // Common sample client_email patterns — the `@y.com` style we saw in
  // the wild, plus `@example.com`, `@test.com`.
  const clientEmail = String(credentials.client_email);
  if (
    /^[^@]+@y\.com$/i.test(clientEmail) ||
    /@example\.com$/i.test(clientEmail) ||
    /@test\.com$/i.test(clientEmail)
  ) {
    return (
      `GOOGLE_APPLICATION_CREDENTIALS client_email looks like a placeholder (${clientEmail}). ` +
      'Replace with a real GCP service-account JSON or use GEMINI_API_KEY instead.'
    );
  }
  return null;
}

export function parseCredentialsInput(input: string) {
  const trimmed = input.trim();
  if (!trimmed) {
    return { credentials: null, keyFile: null };
  }

  if (trimmed.startsWith('{')) {
    // The downstream GoogleAuth library accepts the parsed JSON as
    // `any` — we keep it loose here so existing call sites (project_id,
    // client_email lookups) don't need extra type assertions.
    let parsed: ReturnType<typeof JSON.parse>;
    try {
      parsed = JSON.parse(trimmed);
    } catch (error) {
      throw new Error(`GOOGLE_APPLICATION_CREDENTIALS JSON parse failed: ${String(error)}`);
    }
    // Placeholder guard. See detectPlaceholderCredential
    // above for the rationale. Throwing here means callGeminiWithVertex
    // never reaches the GoogleAuth code path, so the OpenSSL decoder
    // error never surfaces. The operator (or scheduled job) sees a
    // clean message instead.
    const placeholderReason = detectPlaceholderCredential(
      typeof parsed === 'object' && parsed !== null ? parsed : null,
    );
    if (placeholderReason) {
      throw new Error(placeholderReason);
    }
    return { credentials: parsed, keyFile: null };
  }

  return { credentials: null, keyFile: trimmed };
}

export async function callGeminiWithApiKey(
  payload: GeminiCallPayload,
  runtimeConfig: GeminiCredentials,
  modelName: string,
  deps: GeminiTransportDeps = {},
) {
  if (!runtimeConfig.GEMINI_API_KEY) {
    throw new Error('GEMINI_API_KEY is required for the Gemini API call.');
  }

  return withRateLimitRetry(
    async () => {
      const response = await fetchOf(deps)(
        `${GEMINI_API_BASE}/models/${encodeURIComponent(modelName)}:generateContent?key=${runtimeConfig.GEMINI_API_KEY}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
          ...signalInit(deps),
        },
      );

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Gemini API error: ${response.status} ${errorText}`);
      }

      return response.json();
    },
    { label: `gemini-api-key:${modelName}` },
    deps.retry,
  );
}

export async function callGeminiWithVertex(
  payload: GeminiCallPayload,
  runtimeConfig: GeminiCredentials,
  modelName: string,
  deps: GeminiTransportDeps = {},
) {
  if (!runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS) {
    throw new Error('GOOGLE_APPLICATION_CREDENTIALS is required for Vertex AI.');
  }

  const { credentials, keyFile } = parseCredentialsInput(runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS);
  const authOptions = {
    credentials: credentials || undefined,
    keyFile: keyFile || undefined,
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  };
  const auth = makeGeminiAuth(authOptions, deps);

  const projectId =
    credentials?.project_id || (await auth.getProjectId());

  if (!projectId) {
    throw new Error('Vertex AI requires a project_id in GOOGLE_APPLICATION_CREDENTIALS.');
  }

  const location = resolveVertexLocation(modelName);
  const accessToken = await auth.getAccessToken();

  if (!accessToken) {
    throw new Error('Failed to obtain Vertex AI access token.');
  }

  // ── Vertex context caching for the system prompt ───
  //
  // Try to swap the inline systemInstruction for a cached resource
  // reference. Cached input tokens are billed at ~25% — for a 13k
  // system prompt sent on every turn, that's the kind of saving
  // that makes a difference at scale.
  //
  // OPT-IN VIA ENV: gated behind `PHANTOM_VERTEX_CACHE=1`. Some
  // preview-channel models (e.g. gemini-3.1-pro-preview) accept the
  // cachedContents create call but reject subsequent
  // generateContent requests that reference the cache. Rather than
  // enable globally and discover edge cases per-model, the helper is
  // off by default and an operator turns it on once they've validated
  // that their model+region combination supports it. Direct API key path is
  // unaffected either way (caching only touches Vertex).
  let requestPayload: GeminiCallPayload | (Omit<GeminiCallPayload, 'systemInstruction'> & { cachedContent: string }) = payload;
  const cacheEnabled = deps.vertexCacheEnabled
    ? deps.vertexCacheEnabled()
    : process.env.PHANTOM_VERTEX_CACHE === '1';
  const systemPromptText =
    payload.systemInstruction?.parts
      ?.map((p) => ('text' in p && p.text) || '')
      .join('') ?? '';
  if (cacheEnabled && systemPromptText) {
    try {
      const cacheName = await (deps.getSystemPromptCache ?? getOrCreateSystemPromptCache)({
        systemPromptText,
        modelName,
        projectId,
        location,
        accessToken,
      });
      if (cacheName) {
        // Vertex rejects payloads that include BOTH cachedContent
        // and a matching systemInstruction. Drop the inline copy
        // when we're referencing the cache.
        const { systemInstruction: _omit, ...rest } = payload;
        void _omit;
        requestPayload = { ...rest, cachedContent: cacheName };
      }
    } catch (err) {
      // Belt-and-suspenders: any unexpected error from the cache
      // helper falls through to the inline path. The helper itself
      // already returns null on most failure modes, but if a
      // helper-level invariant ever throws, we don't want it to
      // poison the chat turn.
      console.warn(
        'vertex-cache: unexpected error, falling back to inline systemInstruction:',
        err instanceof Error ? err.message : err,
      );
    }
  }

  return withRateLimitRetry(
    async () => {
      const response = await fetchOf(deps)(
        `${VERTEX_API_BASE}/projects/${encodeURIComponent(projectId)}/locations/${location}` +
          `/publishers/google/models/${encodeURIComponent(modelName)}:generateContent`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify(requestPayload),
          ...signalInit(deps),
        },
      );

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Vertex AI error: ${response.status} ${errorText}`);
      }

      return response.json();
    },
    { label: `vertex:${modelName}@${location}` },
    deps.retry,
  );
}

export function isInvalidGeminiApiKeyError(error: unknown) {
  return (
    error instanceof Error &&
    (error.message.includes('API_KEY_INVALID') || error.message.includes('API key not valid'))
  );
}

/**
 * Send a prepared payload: the Gemini API key first, then Vertex when the key
 * is rejected as invalid and a service account is also configured; Vertex
 * alone when there is no key. This is the dispatch `callGemini`,
 * `callGeminiRaw` and `summarizeViaGemini` each repeated. Each caller still
 * supplies its own "no provider" wording, because those messages differ.
 */
export async function callGeminiGenerateContent(
  payload: GeminiCallPayload,
  runtimeConfig: GeminiCredentials,
  modelName: string,
  noProviderMessage: string,
  deps: GeminiTransportDeps = {},
) {
  if (runtimeConfig.GEMINI_API_KEY) {
    try {
      return await callGeminiWithApiKey(payload, runtimeConfig, modelName, deps);
    } catch (error) {
      if (runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS && isInvalidGeminiApiKeyError(error)) {
        return callGeminiWithVertex(payload, runtimeConfig, modelName, deps);
      }
      throw error;
    }
  }

  if (runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS) {
    return callGeminiWithVertex(payload, runtimeConfig, modelName, deps);
  }

  throw new Error(noProviderMessage);
}
