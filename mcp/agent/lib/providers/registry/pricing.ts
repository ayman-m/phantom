/**
 * Cost of one model call from normalized usage.
 *
 * Usage arrives as `NeutralUsage`, where `inputTotal` is every prompt token
 * including cache reads and cache writes, and `cacheWrite` is every cache-write
 * token with `cacheWrite1h` its 1-hour subset. So:
 *
 *   uncached input = inputTotal - cacheRead - cacheWrite
 *   5-minute writes = cacheWrite - cacheWrite1h
 *
 * A model with no price (`pricing: null`), a promotional price past its end
 * date, or a usage shape the price table cannot cover (1-hour writes with no
 * 1-hour price) yields `priced: false` and no dollar figure. Nothing is ever
 * billed at a guessed rate.
 *
 * The long-context tier applies to the whole request when the prompt exceeds
 * the threshold (strictly): `inputMult` scales uncached input, cache reads and
 * cache writes; `outputMult` scales output.
 *
 * Erasable TypeScript only; the imports are type-only.
 */

import type { NeutralUsage } from '../types.ts';
import type { ModelPricing } from './types.ts';

/** The pricing-relevant slice of a registry entry. */
export interface PricedEntry {
  pricing: ModelPricing | null;
  pricingValidUntil?: string;
}

export interface CostComponents {
  /** Uncached input at the base (or long-context) input rate. */
  inputUsd: number;
  cacheReadUsd: number;
  cacheWriteUsd: number;
  outputUsd: number;
  /** What the whole prompt would have cost with no caching at all. */
  uncachedHypotheticalInputUsd: number;
  /** Positive: caching saved money. Negative: cache writes outweighed the reads. */
  cachedSavingsUsd: number;
}

export type CostResult =
  | { priced: true; usd: number; longContext: boolean; components: CostComponents }
  | { priced: false; usd: null; longContext: false; components: null; reason: 'no_pricing' | 'pricing_expired' | 'unpriceable_usage' };

const PER_M = 1_000_000;
const DAY_MS = 86_400_000;

function nonNegative(n: number): number {
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** `validUntil` is an inclusive calendar date (UTC). */
export function pricingExpired(entry: PricedEntry, now: number): boolean {
  if (!entry.pricingValidUntil) return false;
  const end = Date.parse(entry.pricingValidUntil);
  if (!Number.isFinite(end)) return false;
  return now >= end + DAY_MS;
}

export function computeTurnCostUsd(
  usage: NeutralUsage,
  entry: PricedEntry,
  opts: { now?: number } = {},
): CostResult {
  const pricing = entry.pricing;
  if (!pricing) return { priced: false, usd: null, longContext: false, components: null, reason: 'no_pricing' };
  if (pricingExpired(entry, opts.now ?? Date.now())) {
    return { priced: false, usd: null, longContext: false, components: null, reason: 'pricing_expired' };
  }

  const inputTotal = nonNegative(usage.inputTotal);
  const cacheRead = nonNegative(usage.cacheRead);
  const cacheWrite = nonNegative(usage.cacheWrite);
  const cacheWrite1h = Math.min(nonNegative(usage.cacheWrite1h), cacheWrite);
  const cacheWrite5m = cacheWrite - cacheWrite1h;
  const uncached = Math.max(0, inputTotal - cacheRead - cacheWrite);
  const output = nonNegative(usage.output);

  if (cacheWrite5m > 0 && pricing.cacheWrite5mPerM === undefined) {
    return { priced: false, usd: null, longContext: false, components: null, reason: 'unpriceable_usage' };
  }
  if (cacheWrite1h > 0 && pricing.cacheWrite1hPerM === undefined) {
    return { priced: false, usd: null, longContext: false, components: null, reason: 'unpriceable_usage' };
  }

  const tier = pricing.longContext;
  const longContext = Boolean(tier && inputTotal > tier.aboveInputTokens);
  const inMult = longContext && tier ? tier.inputMult : 1;
  const outMult = longContext && tier ? tier.outputMult : 1;

  const inputUsd = (uncached / PER_M) * pricing.inputPerM * inMult;
  const cacheReadUsd = (cacheRead / PER_M) * pricing.cacheReadPerM * inMult;
  const cacheWriteUsd =
    ((cacheWrite5m / PER_M) * (pricing.cacheWrite5mPerM ?? 0) +
      (cacheWrite1h / PER_M) * (pricing.cacheWrite1hPerM ?? 0)) *
    inMult;
  const outputUsd = (output / PER_M) * pricing.outputPerM * outMult;
  const uncachedHypotheticalInputUsd = (inputTotal / PER_M) * pricing.inputPerM * inMult;

  return {
    priced: true,
    usd: inputUsd + cacheReadUsd + cacheWriteUsd + outputUsd,
    longContext,
    components: {
      inputUsd,
      cacheReadUsd,
      cacheWriteUsd,
      outputUsd,
      uncachedHypotheticalInputUsd,
      cachedSavingsUsd: uncachedHypotheticalInputUsd - (inputUsd + cacheReadUsd + cacheWriteUsd),
    },
  };
}
