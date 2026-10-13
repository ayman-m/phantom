/**
 * Per-model context-window caps for budget math.
 *
 * The data layer for token-aware budgeting: history is trimmed to each model's
 * context window rather than to a fixed message count.
 *
 * **Source of truth.** The model registry (lib/providers/registry). A cap is
 * the registry's context window for the model, which is the live provider
 * value when a live list has been fetched and the curated value otherwise.
 * There is no second table here.
 *
 * **Lookup.** Exact model id, case-insensitive, with an optional provider
 * prefix (`vertex/gemini-3.1-pro-preview`). A model the registry does not know
 * gets the single documented default (200k). A model's lifecycle never changes
 * its cap: a deprecated or retired model budgets as it always did.
 *
 * **What this does NOT cap.** The output side. Phantom sets no
 * `maxOutputTokens` cap for Gemini, so the model writes up to its natural
 * ceiling. The cap returned here is the *input* budget: system prompt + tools
 * + history + new turn must fit under it, with `DEFAULT_RESERVED_OUTPUT_TOKENS`
 * held back for the response, and the registry's tokenizer factor scaling the
 * heuristic token estimate for models that tokenize more densely.
 *
 * **Adding a model.** Add it to the provider's curated catalog under
 * lib/providers/registry; nothing here changes.
 */

import { DEFAULT_CONTEXT_CAP, lookupModelFacts } from './providers/registry/lookup.ts';

/**
 * Tokens reserved for the model's own output when computing how much of the
 * context window is left for input (system + tools + history). Matches
 * gemini-3.1-pro-preview's natural output ceiling now that Phantom does not
 * cap maxOutputTokens.
 *
 * Both this module's `computeInputBudget` default (the history budget walk)
 * and the context-window guard in app/api/chat/route.ts reference this one
 * export, so they cannot disagree on how much room to reserve for output.
 */
export const DEFAULT_RESERVED_OUTPUT_TOKENS = 65_536;

/**
 * Resolve a context-window cap (in tokens) for a model name.
 *
 * Returns the documented default (200k) for an unknown model, a model whose
 * window is not stated, and empty or undefined input.
 */
export function resolveContextCap(modelName: string | undefined): number {
  const window = lookupModelFacts(modelName)?.contextWindow;
  return typeof window === 'number' && window > 0 ? window : DEFAULT_CONTEXT_CAP;
}

/**
 * How many tokens the model produces for text the chars/4 heuristic counts as
 * one token: 1 for most models, 1.3 for the newer Claude tokenizer.
 */
export function resolveTokenizerFactor(modelName: string | undefined): number {
  return lookupModelFacts(modelName)?.tokenizerFactor ?? 1;
}

/**
 * Compute the *input* token budget: how much we can spend on history + system
 * prompt + tools + new turn, given a model's context cap and the configured
 * output budget.
 *
 * The fudge factor is intentional: real-world token counting can undercount by
 * 5-15% on code-heavy or non-English text, so we reserve a safety margin. We
 * use 70% as the *target*, which is more aggressive than 50% but safer than
 * 100%. A model whose provider caps the prompt below its window (`maxInput`)
 * is bounded by that cap instead.
 */
export function computeInputBudget(
  modelName: string | undefined,
  reservedForOutput = DEFAULT_RESERVED_OUTPUT_TOKENS,
): number {
  const facts = lookupModelFacts(modelName);
  const cap = resolveContextCap(modelName);
  const room = Math.min(cap - reservedForOutput, facts?.maxInput ?? Infinity);
  const factor = facts?.tokenizerFactor ?? 1;
  // Reserve output budget plus a 30% safety margin against tokenizer
  // undercounting. Gives roughly: 1M-token Gemini -> ~700k for input.
  const usable = Math.floor((room * 0.7) / factor);
  return Math.max(8_000, usable);
}
