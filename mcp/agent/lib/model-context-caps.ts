/**
 * Per-model context-window caps for budget math.
 *
 * This module is the data layer for token-aware budgeting: history is
 * trimmed to each model's context window rather than to a fixed
 * message count.
 *
 * **Source of truth.** Caps come from each provider's published model
 * card. Where a model has multiple variants (preview, GA), we record
 * the most generous publicly-documented cap; in practice operators
 * who need exact billing should call the provider's `count_tokens`
 * endpoint, which is out of scope here.
 *
 * **Lookup strategy.** Exact match first (`gemini-2.5-pro` ↔ map
 * key), then prefix match against substring patterns (so unknown
 * model variants like `gemini-3-pro-preview-05` still resolve to a
 * sensible cap via the `gemini-3` prefix), then a global fallback.
 *
 * **What this does NOT cap.** The output side. Phantom sets no
 * `maxOutputTokens` cap — the model writes up to its natural ceiling. The cap returned here is the *input* budget —
 * system prompt + tools + history + new turn must fit under it, with
 * `DEFAULT_RESERVED_OUTPUT_TOKENS` (below) held back for the
 * response.
 *
 * **Adding a model.** Add an entry to `MODEL_CAP` (exact match) or
 * to `PREFIX_CAPS` (substring family). Test with the model name the
 * chat handler actually receives via `body.model` (sometimes
 * provider-prefixed: `vertex/gemini-2.5-pro`).
 */

/** Phantom-default cap if nothing matches. Set high enough to not
 *  over-restrict modern models, low enough that older models don't
 *  blow up. 200k is roughly the Claude 3.5 Sonnet GA window — a
 *  reasonable midpoint. */
const DEFAULT_CAP = 200_000;

/** Exact-match table (case-insensitive). */
const MODEL_CAP: Record<string, number> = {
  // Gemini 2.5 family — both pro and flash advertise 1M+
  'gemini-2.5-pro': 2_000_000,
  'gemini-2.5-flash': 1_000_000,
  'gemini-2.5-flash-preview': 1_000_000,
  'gemini-2.0-pro': 2_000_000,
  'gemini-2.0-flash': 1_000_000,

  // Gemini 1.5 family
  'gemini-1.5-pro': 2_000_000,
  'gemini-1.5-flash': 1_000_000,
  'gemini-1.5-flash-8b': 1_000_000,

  // Gemini 3.x preview chain — Phantom's bundle defaults to one of
  // these via runtimeConfig.GEMINI_MODEL ?? 'gemini-3.1-pro-preview'.
  'gemini-3.1-pro-preview': 1_000_000,
  'gemini-3-pro-preview': 1_000_000,
  // gemini-3.7-flash is the current Flash-tier flagship. It is also
  // listed in provider.yaml's spec.models[].
  'gemini-3.7-flash': 1_000_000,

  // Claude family
  'claude-3.5-sonnet': 200_000,
  'claude-3-5-sonnet': 200_000,
  'claude-3.5-haiku': 200_000,
  'claude-3-5-haiku': 200_000,
  'claude-3-opus': 200_000,
  // Claude Opus 4.7 with the 1M-context flag (matches OpenClaw's
  // special-case in src/agents/context.ts:isClaudeOpus47Model).
  'claude-opus-4.7': 1_048_576,
  'claude-opus-4-7': 1_048_576,

  // OpenAI family (in case Phantom adds an OpenAI provider later)
  'gpt-4o': 128_000,
  'gpt-4o-mini': 128_000,
  'gpt-4-turbo': 128_000,
};

/**
 * Substring → cap mapping for unknown variants. Order matters:
 * longer/more-specific prefixes first so `gemini-3-pro-preview-05`
 * matches `gemini-3` and not just `gemini`.
 */
const PREFIX_CAPS: Array<[string, number]> = [
  ['gemini-3', 1_000_000],
  ['gemini-2.5', 1_000_000],
  ['gemini-2.0', 1_000_000],
  ['gemini-1.5', 1_000_000],
  ['gemini', 1_000_000],
  ['claude-opus-4', 1_048_576],
  ['claude-3', 200_000],
  ['claude', 200_000],
  ['gpt-4', 128_000],
  ['gpt-3.5', 16_000],
  ['gpt', 16_000],
];

/**
 * Resolve a context-window cap (in tokens) for a model name.
 *
 * Returns DEFAULT_CAP (200k) if nothing matches, which is a
 * conservative midpoint that won't over-restrict modern models nor
 * blow up older ones. Empty / undefined input also gets the default.
 */
export function resolveContextCap(modelName: string | undefined): number {
  if (!modelName) return DEFAULT_CAP;
  const norm = modelName.trim().toLowerCase();
  // Strip provider prefixes like "vertex/" or "anthropic/" so we
  // match the bare model identifier.
  const bare = norm.includes('/') ? norm.slice(norm.lastIndexOf('/') + 1) : norm;

  if (bare in MODEL_CAP) return MODEL_CAP[bare];
  for (const [prefix, cap] of PREFIX_CAPS) {
    if (bare.startsWith(prefix)) return cap;
  }
  return DEFAULT_CAP;
}

/**
 * Tokens reserved for the model's own output when computing how much
 * of the context window is left for input (system + tools + history).
 * Matches gemini-3.1-pro-preview's natural output ceiling now that
 * Phantom does not cap maxOutputTokens (see the file
 * header's "What this does NOT cap" note).
 *
 * Both this module's `computeInputBudget` default (the history budget
 * walk) and the context-window guard in app/api/chat/route.ts
 * reference this one export, so they cannot disagree on how much
 * room to reserve for output.
 */
export const DEFAULT_RESERVED_OUTPUT_TOKENS = 65_536;

/**
 * Compute the *input* token budget — how much we can spend on
 * history + system prompt + tools + new turn — given a model's
 * context cap and the configured output budget.
 *
 * The fudge factor is intentional: real-world token counting can
 * undercount by 5–15% on code-heavy or non-English text, so we
 * reserve a safety margin. OpenClaw uses 50% as `MIN_PROMPT_BUDGET_RATIO`
 * (50% MUST be available for prompt content); we use 70% as the
 * *target*, which is more aggressive but safer than 100%.
 */
export function computeInputBudget(
  modelName: string | undefined,
  reservedForOutput = DEFAULT_RESERVED_OUTPUT_TOKENS,
): number {
  const cap = resolveContextCap(modelName);
  // Reserve output budget plus a 30% safety margin against tokenizer
  // undercounting. Gives roughly: 1M-token Gemini → ~700k for input.
  const usable = Math.floor((cap - reservedForOutput) * 0.7);
  return Math.max(8_000, usable);
}
