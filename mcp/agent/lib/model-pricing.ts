/**
 * Model pricing, read from the model registry.
 *
 * There is no rate table here. Per-model rates live in the provider catalogs
 * under lib/providers/registry, with the date each was last checked; the cost
 * arithmetic is `computeTurnCostUsd` in lib/providers/registry/pricing.ts,
 * and turning a call's usage into an audit row is lib/cost-rows.ts. This
 * module keeps the price lookup and the dollar formatting.
 *
 * A model the registry does not know, or one with no known price, is
 * **unpriced**: its cost is null, never an estimate from a neighbouring model
 * and never 0.
 *
 * This file is imported by client components (for `formatUsd`), so it must
 * stay free of Node-only imports.
 */

import { lookupModelFacts } from './providers/registry/lookup.ts';
import { pricingExpired } from './providers/registry/pricing.ts';
import type { ModelPricing } from './providers/registry/types.ts';

export type { ModelPricing } from './providers/registry/types.ts';

/** The model's rates, or null when it is unknown, unpriced, or its price has expired. */
export function resolveModelPricing(model: string): ModelPricing | null {
  const facts = lookupModelFacts(model);
  if (!facts || !facts.pricing || pricingExpired(facts, Date.now())) return null;
  return facts.pricing;
}

/** Human-readable USD format with appropriate precision.
 *  Sub-cent values get 4 decimals; sub-dollar 3; dollar+ 2. */
export function formatUsd(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.001) return `$${usd.toFixed(5)}`;
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

/** Like `formatUsd`, but a null cost (an unpriced call) reads "unpriced", not "$0". */
export function formatCostOrUnpriced(usd: number | null | undefined): string {
  return typeof usd === "number" && Number.isFinite(usd) ? formatUsd(usd) : "unpriced";
}
