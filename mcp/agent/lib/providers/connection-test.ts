/**
 * The Test Connection action behind `POST /api/agent/providers/<id>/test`.
 *
 * Body: `{ api_key?: string, base_url?: string, organization?: string,
 * project?: string }` (the last two are OpenAI's optional routing headers).
 *
 *   - An `api_key` of `""` or the sentinel `"***"` means "use the key that is
 *     saved", resolved here on the server; the key never travels to the
 *     browser and back.
 *   - A saved key is only ever sent to the base URL it was saved with. Asking
 *     to test the saved key against a different base URL is refused, so this
 *     action cannot be used to carry a stored key to another host; the
 *     operator saves the new base URL first, or types the key again.
 *   - A typed key is tested against the base URL in the form; an empty base URL
 *     means the provider's default.
 *   - The organization and project in the form always win over the saved ones
 *     (an empty value means none), also with a saved key. They only choose
 *     which account the same host bills, so they cannot carry the key anywhere.
 *
 * The check itself is the adapter's `testConnection`, a `GET /v1/models` that
 * costs no tokens, so every base URL goes through the outbound-URL guard.
 * Each test writes one audit row, `provider_test`, holding `{provider, ok,
 * status}` and never the key.
 *
 * The result is for an HTTP 200 response in every case (a failed test is a
 * normal answer for the Providers page), shaped `{status, message,
 * modelCount?}`.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { redactSecrets } from './errors.ts';
import { ANTHROPIC_DEFAULT_BASE, OPENAI_DEFAULT_BASE } from './registry/live.ts';
import type { ProviderAdapter, ProviderCreds, ProviderId } from './types.ts';

export const KEY_SENTINEL = '***';

export interface ConnectionTestResult {
  status: 'success' | 'error';
  message: string;
  modelCount?: number;
}

export interface ConnectionTestAudit {
  provider: ProviderId;
  ok: boolean;
  /** The provider's HTTP status when it answered, else null. */
  status: number | null;
}

export interface ConnectionTestDeps {
  adapter: ProviderAdapter;
  /** The saved credentials; null when the provider is not configured. */
  resolveCreds: (provider: ProviderId) => Promise<ProviderCreds | null>;
  audit: (row: ConnectionTestAudit) => Promise<void> | void;
}

const DEFAULT_BASES: Partial<Record<ProviderId, string>> = {
  anthropic: ANTHROPIC_DEFAULT_BASE,
  openai: OPENAI_DEFAULT_BASE,
};

const PROVIDER_NAMES: Partial<Record<ProviderId, string>> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
};

/** Compare-friendly form of a base URL: lowercase origin, no trailing slash. */
export function normalizeBaseUrl(raw: string): string {
  const text = raw.trim();
  try {
    const url = new URL(text);
    return `${url.origin.toLowerCase()}${url.pathname.replace(/\/+$/, '')}`;
  } catch {
    return text.replace(/\/+$/, '');
  }
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export async function runProviderConnectionTest(
  provider: ProviderId,
  body: unknown,
  deps: ConnectionTestDeps,
): Promise<ConnectionTestResult> {
  const name = PROVIDER_NAMES[provider] ?? provider;
  const input = typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
  if (!input) return { status: 'error', message: 'Request body must be a JSON object.' };

  const typedKey = (asString(input.api_key) ?? '').trim();
  const requestedBase = (asString(input.base_url) ?? '').trim();
  const useSaved = typedKey === '' || typedKey === KEY_SENTINEL;
  const defaultBase = DEFAULT_BASES[provider] ?? '';

  let creds: ProviderCreds;
  if (useSaved) {
    const saved = await deps.resolveCreds(provider);
    if (!saved?.apiKey) {
      return { status: 'error', message: `No ${name} API key is saved yet. Enter a key above, then test again.` };
    }
    const savedBase = normalizeBaseUrl(saved.baseUrl?.trim() || defaultBase);
    if (requestedBase && normalizeBaseUrl(requestedBase) !== savedBase) {
      return {
        status: 'error',
        message:
          'The saved key is only used with the base URL it was saved with. ' +
          'Save the new base URL first, or enter the API key again to test it.',
      };
    }
    creds = { ...saved };
  } else {
    creds = { apiKey: typedKey };
    if (requestedBase) creds.baseUrl = requestedBase;
  }
  if (provider === 'openai') {
    const organization = asString(input.organization);
    const project = asString(input.project);
    if (organization !== undefined) creds.organization = organization.trim() || undefined;
    if (project !== undefined) creds.project = project.trim() || undefined;
  }

  const outcome = await deps.adapter.testConnection(creds);
  try {
    await deps.audit({ provider, ok: outcome.ok, status: outcome.status ?? null });
  } catch {
    // An audit failure never changes what the operator is told.
  }
  const result: ConnectionTestResult = {
    status: outcome.ok ? 'success' : 'error',
    message: redactSecrets(outcome.message),
  };
  if (outcome.modelCount !== undefined) result.modelCount = outcome.modelCount;
  return result;
}
