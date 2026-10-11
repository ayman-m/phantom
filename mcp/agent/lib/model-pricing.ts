/**
 * Model pricing table
 *
 * Per-model dollar-per-million-tokens rates for the Vertex / direct
 * Gemini models Phantom supports today. Used to compute per-turn USD
 * cost from `usageMetadata.{promptTokenCount, cachedContentTokenCount,
 * candidatesTokenCount}`.
 *
 * Pricing source: Vertex AI public pricing page as of 2026-05.
 * https://cloud.google.com/vertex-ai/generative-ai/pricing
 *
 * Cached input bills at ~25% of standard input rate (Vertex
 * cachedContents discount). We split the input total into cached
 * + uncached portions and apply rates separately.
 *
 * Adding a model: append an entry to `MODEL_PRICING_TABLE`. Unknown
 * models fall through to `FALLBACK_PRICING` (a conservative
 * gemini-2.5-pro-equivalent rate) so we always emit a non-zero cost
 * estimate even for new models we haven't priced yet.
 */

export interface ModelPricing {
  /** USD per million input tokens (uncached). */
  inputPerM: number;
  /** USD per million input tokens (cached portion). Typically
   *  inputPerM × 0.25 — the Vertex cachedContents discount. */
  cachedInputPerM: number;
  /** USD per million output tokens. */
  outputPerM: number;
}

/**
 * Known models. Keys are matched substring-style (longest-prefix
 * wins) so operator-facing model strings like
 * "gemini-2.5-pro-preview-0514" still match a table entry of
 * "gemini-2.5-pro".
 */
export const MODEL_PRICING_TABLE: Record<string, ModelPricing> = {
  // Default model. Pricing as of 2026-05.
  "gemini-3.1-pro-preview": {
    inputPerM: 2.5,
    cachedInputPerM: 0.625,
    outputPerM: 12.0,
  },
  "gemini-3.0-pro": {
    inputPerM: 2.0,
    cachedInputPerM: 0.5,
    outputPerM: 10.0,
  },
  "gemini-2.5-pro": {
    inputPerM: 1.25,
    cachedInputPerM: 0.3125,
    outputPerM: 5.0,
  },
  "gemini-2.5-flash": {
    inputPerM: 0.075,
    cachedInputPerM: 0.01875,
    outputPerM: 0.3,
  },
  "gemini-2.5-flash-lite": {
    inputPerM: 0.0375,
    cachedInputPerM: 0.009375,
    outputPerM: 0.15,
  },
};

/** Fallback for unknown models — uses gemini-2.5-pro-class
 *  pricing so estimates aren't wildly off in either direction. */
export const FALLBACK_PRICING: ModelPricing = {
  inputPerM: 1.25,
  cachedInputPerM: 0.3125,
  outputPerM: 5.0,
};

/** Resolve pricing for a model name. Longest-prefix match against
 *  the known table, falling back to FALLBACK_PRICING. */
export function resolveModelPricing(model: string): ModelPricing {
  if (!model) return FALLBACK_PRICING;
  const candidates = Object.keys(MODEL_PRICING_TABLE)
    .filter((k) => model.startsWith(k))
    .sort((a, b) => b.length - a.length);
  if (candidates.length > 0) {
    return MODEL_PRICING_TABLE[candidates[0]];
  }
  return FALLBACK_PRICING;
}

/**
 * Compute USD cost for one turn given the Vertex usage metadata.
 *
 * Input shape:
 *   inputTokens          total input tokens (pre-cache split)
 *   cachedInputTokens    cached portion (subset of inputTokens)
 *   outputTokens         model-emitted tokens
 *   model                model name (best-effort match)
 *
 * Returns:
 *   { usd, components } — USD float and a breakdown by component
 *   so the UI can show "you paid $X for output, $Y for input,
 *   $Z saved by caching".
 */
export function computeTurnCostUsd(args: {
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  model: string;
}): {
  usd: number;
  components: {
    inputUsd: number;
    cachedInputUsd: number;
    outputUsd: number;
    /** What the input portion would have cost without caching.
     *  Useful for ROI display: usd_saved = uncachedHypotheticalUsd
     *  - inputUsd. */
    uncachedHypotheticalInputUsd: number;
    pricing: ModelPricing;
  };
} {
  const pricing = resolveModelPricing(args.model);
  const cached = Math.max(0, args.cachedInputTokens);
  const uncached = Math.max(0, args.inputTokens - cached);
  const inputUsd = (uncached / 1_000_000) * pricing.inputPerM;
  const cachedInputUsd = (cached / 1_000_000) * pricing.cachedInputPerM;
  const outputUsd = (args.outputTokens / 1_000_000) * pricing.outputPerM;
  const uncachedHypotheticalInputUsd =
    ((uncached + cached) / 1_000_000) * pricing.inputPerM;
  return {
    usd: inputUsd + cachedInputUsd + outputUsd,
    components: {
      inputUsd,
      cachedInputUsd,
      outputUsd,
      uncachedHypotheticalInputUsd,
      pricing,
    },
  };
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
