/**
 * Conservative token estimator for chat-context budgeting.
 *
 * Used by `loadSessionHistory()` and other code
 * paths that need to decide "will this fit in the model's context
 * window?" without paying the cost of a real tokenizer.
 *
 * **Why a heuristic, not a real tokenizer.** Loading a tokenizer
 * (tiktoken, llama-3, etc.) for the agent runtime would add tens of
 * MB to the bundle and hundreds of ms per request — out of proportion
 * for what we actually need (a budget cap, not byte-perfect billing).
 * The four-chars-per-token approximation is a well-established floor
 * across BPE-ish tokenizers (GPT-3.5/4: ~4 chars/tok English, more
 * for code; Claude: similar; Gemini: similar). It will *underestimate*
 * for non-English text and code-heavy turns, which is the desirable
 * direction — when in doubt, we'd rather drop a turn than overflow
 * the model's cap.
 *
 * **Per-message overhead.** Every message in a Gemini contents array
 * has framing bytes (role marker, parts wrapper, JSON envelope) that
 * the tokenizer counts but the text content does not. We bake a
 * conservative +5 tokens per message to account for that. OpenClaw
 * uses similar fudge factors; the exact number doesn't matter much
 * as long as it's nonzero.
 *
 * **Where this is wrong.** Function-call parts and function-response
 * parts (Gemini's structured tool I/O) tokenize differently from raw
 * text. We don't currently emit those during replay (plain-text
 * observations are used instead), so the heuristic stays
 * accurate for our actual payload shape. If we add structured
 * function calls later, this estimator will need a per-part
 * specialization.
 *
 * Signed off as "good enough" until we observe overflow errors at
 * the Vertex layer; at that point we'd either tighten the multiplier
 * or import a real tokenizer for the affected model family.
 */

/** Rough chars-per-token for BPE-ish English+code text. */
const CHARS_PER_TOKEN = 4;

/** Per-message envelope overhead (role marker + parts wrapper + JSON
 *  framing). Five tokens covers Gemini's contents-shape and Anthropic
 *  messages-shape both. */
const PER_MESSAGE_OVERHEAD = 5;

/**
 * Estimate the token cost of a single text fragment.
 *
 * Returns at least 1 token for any non-empty string so empty-ish
 * inputs ("ok", ".") don't claim zero budget.
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / CHARS_PER_TOKEN));
}

/**
 * Estimate the token cost of a single message in a Gemini-style
 * contents array. Adds the framing overhead on top of the content
 * estimate.
 */
export function estimateMessageTokens(text: string): number {
  return estimateTokens(text) + PER_MESSAGE_OVERHEAD;
}
