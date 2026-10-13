/**
 * Synchronous read side of the registry: the curated catalogs, the provider
 * order, and "what do we know about this model name" for code that cannot
 * await (the context-window budget walk, the cost calculation).
 *
 * Facts come from the last merged registry list when one has been published
 * (so a live context window wins), else from the curated catalog. A model's
 * lifecycle never changes its facts: a deprecated or retired model keeps the
 * cap and price it had, so history already sent on it still budgets and prices
 * the same way.
 *
 * Pure data and functions with no Node imports, so client components may
 * import it through lib/model-pricing.ts. Erasable TypeScript only.
 */

import type { ProviderId } from '../types.ts';
import { ANTHROPIC_CATALOG } from './catalog-anthropic.ts';
import { OPENAI_CATALOG } from './catalog-openai.ts';
import { VERTEX_CATALOG } from './catalog-vertex.ts';
import type { CuratedModel } from './types.ts';

/** The order providers are listed in, and the order bare ids are searched. */
export const PROVIDER_ORDER: readonly ProviderId[] = ['vertex', 'anthropic', 'openai'];

export const PROVIDER_LABELS: Record<ProviderId, string> = {
  vertex: 'Google (Vertex AI and Gemini API)',
  anthropic: 'Anthropic',
  openai: 'OpenAI',
};

export const CURATED_CATALOG: readonly CuratedModel[] = [
  ...VERTEX_CATALOG,
  ...ANTHROPIC_CATALOG,
  ...OPENAI_CATALOG,
];

/**
 * The single context-window cap used for a model the registry does not know.
 * 200k is a midpoint: high enough not to over-restrict a modern model, low
 * enough that an older one is not overrun.
 */
export const DEFAULT_CONTEXT_CAP = 200_000;

/** What callers outside the registry read about a model. */
export type ModelFacts = Omit<CuratedModel, 'unverified' | 'recommended'>;

let published: readonly ModelFacts[] = [];

/** Called by the registry after each merge so the sync lookups see live values. */
export function publishModelFacts(entries: readonly ModelFacts[]): void {
  published = entries;
}

export function parseModelInput(input: string): { provider?: ProviderId; model: string } {
  const text = input.trim();
  const slash = text.indexOf('/');
  if (slash < 0) return { model: text };
  const prefix = text.slice(0, slash).toLowerCase();
  const provider = PROVIDER_ORDER.find((p) => p === prefix);
  if (provider) return { provider, model: text.slice(slash + 1) };
  // Not a provider prefix: keep the last path segment, as bare ids always were.
  return { model: text.slice(text.lastIndexOf('/') + 1) };
}

function pick(pool: readonly ModelFacts[], provider: ProviderId | undefined, wanted: string): ModelFacts | null {
  const hits = pool.filter(
    (m) => m.model.toLowerCase() === wanted && (provider === undefined || m.provider === provider),
  );
  if (hits.length === 0) return null;
  hits.sort((a, b) => PROVIDER_ORDER.indexOf(a.provider) - PROVIDER_ORDER.indexOf(b.provider));
  return hits[0];
}

/**
 * Facts for "provider/model" or a bare model id; null when the registry does
 * not know the model. A bare id present under several providers resolves in
 * provider order (vertex, anthropic, openai), which only matters for callers
 * that cannot carry a provider.
 */
export function lookupModelFacts(input: string | undefined): ModelFacts | null {
  if (!input) return null;
  const { provider, model } = parseModelInput(input);
  if (!model) return null;
  const wanted = model.toLowerCase();
  return pick(published, provider, wanted) ?? pick(CURATED_CATALOG, provider, wanted);
}
