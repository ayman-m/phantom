/**
 * Turn what an operator, a job, a skill or a session wrote into one model.
 *
 * Accepted: the canonical "provider/model", or a bare model id. A bare id
 * resolves only when exactly one configured provider has it; two (for example
 * a Claude id offered by both Vertex and Anthropic) is AMBIGUOUS and lists the
 * qualified options. Bare ids are an input syntax, not a fallback chain: the
 * result always carries the canonical ref, and nothing is silently swapped for
 * a default.
 *
 * Failures carry a stable code, an operator-readable message, and up to three
 * selectable suggestions.
 *
 * The caller passes the entries to resolve against, including retired ones
 * (`list({includeRetired: true})`), so a retired id says so instead of
 * claiming the model is unknown.
 *
 * Erasable TypeScript only; the imports are type-only plus the provider list.
 */

import type { ModelRef, ProviderId } from '../types.ts';
import { PROVIDER_LABELS, PROVIDER_ORDER } from './lookup.ts';
import type { ModelEntry } from './types.ts';

export type ResolveErrorCode =
  | 'AMBIGUOUS'
  | 'MODEL_UNKNOWN'
  | 'PROVIDER_NOT_CONFIGURED'
  | 'MODEL_NOT_SELECTABLE';

export type ResolveResult =
  | { ok: true; ref: ModelRef; canonical: string; entry: ModelEntry }
  | {
      ok: false;
      code: ResolveErrorCode;
      message: string;
      /** Selectable refs close to what was asked for. */
      suggestions: string[];
      /** AMBIGUOUS: the qualified refs that would each resolve. */
      options?: string[];
    };

function distance(a: string, b: string): number {
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let diag = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const up = prev[j];
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diag + (a[i - 1] === b[j - 1] ? 0 : 1));
      diag = up;
    }
  }
  return prev[b.length];
}

function suggest(entries: readonly ModelEntry[], wanted: string): string[] {
  const w = wanted.toLowerCase();
  return entries
    .filter((e) => e.selectable)
    .map((e) => {
      const id = e.model.toLowerCase();
      const near = id.includes(w) || w.includes(id) ? 0 : distance(id, w);
      return { ref: e.ref, score: near };
    })
    .sort((a, b) => a.score - b.score || a.ref.localeCompare(b.ref))
    .slice(0, 3)
    .map((s) => s.ref);
}

function fail(
  code: ResolveErrorCode,
  message: string,
  entries: readonly ModelEntry[],
  wanted: string,
  options?: string[],
): ResolveResult {
  return { ok: false, code, message, suggestions: suggest(entries, wanted), ...(options ? { options } : {}) };
}

function success(entry: ModelEntry): ResolveResult {
  return { ok: true, ref: { provider: entry.provider, model: entry.model }, canonical: entry.ref, entry };
}

function configuredProviders(entries: readonly ModelEntry[]): Set<ProviderId> {
  const set = new Set<ProviderId>();
  for (const e of entries) if (e.providerState !== 'not_configured') set.add(e.provider);
  return set;
}

function checkSelectable(entry: ModelEntry, entries: readonly ModelEntry[], wanted: string): ResolveResult {
  if (entry.selectable) return success(entry);
  return fail(
    'MODEL_NOT_SELECTABLE',
    `${entry.ref} cannot be used right now${entry.reason ? `: ${entry.reason}` : '.'}`,
    entries,
    wanted,
  );
}

export function resolveModelRef(input: string, entries: readonly ModelEntry[]): ResolveResult {
  const text = (input ?? '').trim();
  if (!text) return fail('MODEL_UNKNOWN', 'No model was named.', entries, '');
  const configured = configuredProviders(entries);

  const slash = text.indexOf('/');
  if (slash >= 0) {
    const prefix = text.slice(0, slash).toLowerCase();
    const model = text.slice(slash + 1);
    const provider = PROVIDER_ORDER.find((p) => p === prefix);
    if (!provider) {
      return fail('MODEL_UNKNOWN', `"${prefix}" is not a model provider. Use provider/model, for example vertex/gemini-3.1-pro-preview.`, entries, model);
    }
    if (!configured.has(provider)) {
      return fail('PROVIDER_NOT_CONFIGURED', `The ${PROVIDER_LABELS[provider]} provider is not configured. Add its credentials on the Providers page.`, entries, model);
    }
    const hit = entries.find((e) => e.provider === provider && e.model.toLowerCase() === model.toLowerCase());
    if (!hit) {
      return fail('MODEL_UNKNOWN', `${provider}/${model} is not a known model.`, entries, model);
    }
    return checkSelectable(hit, entries, model);
  }

  const wanted = text.toLowerCase();
  const matches = entries.filter((e) => e.model.toLowerCase() === wanted);
  const live = matches.filter((e) => configured.has(e.provider));
  if (live.length === 1) return checkSelectable(live[0], entries, text);
  if (live.length > 1) {
    const options = live.map((e) => e.ref);
    return fail(
      'AMBIGUOUS',
      `"${text}" is offered by more than one provider. Use one of: ${options.join(', ')}.`,
      entries,
      text,
      options,
    );
  }
  if (matches.length > 0) {
    const names = [...new Set(matches.map((e) => PROVIDER_LABELS[e.provider]))].join(' or ');
    return fail('PROVIDER_NOT_CONFIGURED', `${text} needs the ${names} provider, which is not configured. Add its credentials on the Providers page.`, entries, text);
  }
  return fail('MODEL_UNKNOWN', `"${text}" is not a known model.`, entries, text);
}
