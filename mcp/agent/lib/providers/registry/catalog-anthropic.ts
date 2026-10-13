/**
 * Curated Claude catalog (provider "anthropic").
 *
 * Source: the vendor's model overview, pricing, thinking, effort and error
 * pages, read 2026-10-13. Every price below is restated with that date.
 * The live list (`GET /v1/models`) overrides context window, output cap,
 * thinking and effort capabilities and lifecycle; this table wins on pricing,
 * how "thinking off" is requested, and forced tool choice, none of which the
 * live list carries.
 *
 * Deliberately absent: Haiku 4.5 (retires 2026-10-15), Sonnet 4.5 (deprecated,
 * retires 2026-11-30), the limited-availability Mythos models, and anything
 * older. A live key that can see them still lists them (unpriced, selectable).
 *
 * Retirement dates are the vendor's "not sooner than" commitments, so they are
 * not stored; the live list reports a real `retires_at` once one is set.
 *
 * Erasable TypeScript only.
 */

import type { CuratedModel, ModelPricing } from './types.ts';

const VERIFIED = '2026-10-13';

/** The newer tokenizer (Opus 4.7 onwards) produces about 30% more tokens for the same text. */
const NEW_TOKENIZER = 1.3;

const CLAUDE_5_BASE = {
  provider: 'anthropic',
  kind: 'chat',
  contextWindow: 1_000_000,
  tokenizerFactor: NEW_TOKENIZER,
  tools: true,
  pricingVerified: VERIFIED,
  lifecycle: { stage: 'ga' },
} as const;

const EFFORTS_5_5 = ['low', 'medium', 'high', 'xhigh', 'max'] as const;
// capabilities.effort always lists these four; xhigh is the nullable extra.
const EFFORTS_BASE = ['low', 'medium', 'high', 'max'] as const;

function cacheTiers(input: number, readMult: number): Pick<ModelPricing, 'cacheReadPerM' | 'cacheWrite5mPerM' | 'cacheWrite1hPerM'> {
  return {
    cacheReadPerM: round(input * readMult),
    cacheWrite5mPerM: round(input * 1.25),
    cacheWrite1hPerM: round(input * 2),
  };
}

function round(n: number): number {
  return Math.round(n * 1e6) / 1e6;
}

export const ANTHROPIC_CATALOG: readonly CuratedModel[] = [
  {
    ...CLAUDE_5_BASE,
    model: 'claude-fable-5-1',
    displayName: 'Claude Fable 5.1',
    maxOutput: 128_000,
    // Forced tool use returns 400 on this model.
    forcedToolChoice: false,
    // Adaptive always; "disabled" is a 400, so off means the lowest effort.
    thinking: { on: 'adaptive', offMode: 'low_effort', efforts: EFFORTS_5_5, defaultEffort: 'high' },
    pricing: { inputPerM: 10, outputPerM: 50, ...cacheTiers(10, 0.025) },
  },
  {
    ...CLAUDE_5_BASE,
    model: 'claude-opus-5-5',
    displayName: 'Claude Opus 5.5',
    maxOutput: 128_000,
    forcedToolChoice: false,
    thinking: { on: 'adaptive', offMode: 'low_effort', efforts: EFFORTS_5_5, defaultEffort: 'medium' },
    pricing: { inputPerM: 4, outputPerM: 20, ...cacheTiers(4, 0.05) },
  },
  {
    ...CLAUDE_5_BASE,
    model: 'claude-sonnet-5-5',
    displayName: 'Claude Sonnet 5.5',
    maxOutput: 128_000,
    forcedToolChoice: false,
    // "disabled" is a 400; between_tools skips up-front thinking (efforts up to high only).
    thinking: { on: 'adaptive', offMode: 'between_tools', efforts: EFFORTS_5_5, defaultEffort: 'high' },
    pricing: { inputPerM: 2, outputPerM: 10, ...cacheTiers(2, 0.05) },
    recommended: true,
  },
  {
    ...CLAUDE_5_BASE,
    model: 'claude-haiku-5-5',
    displayName: 'Claude Haiku 5.5',
    maxOutput: 128_000,
    // Not on the vendor's list of models that reject forced tool use; that
    // absence is the only evidence, and the adapter still skips forcing when
    // thinking is on.
    forcedToolChoice: true,
    thinking: { on: 'adaptive', offMode: 'disabled', efforts: EFFORTS_5_5, defaultEffort: 'medium' },
    pricing: {
      inputPerM: 0.1,
      outputPerM: 0.5,
      ...cacheTiers(0.1, 0.1),
      // A prompt over 100K tokens pays the higher row for the whole request:
      // 0.50 / 2.50 per MTok, every rate five times the base.
      longContext: { aboveInputTokens: 100_000, inputMult: 5, outputMult: 5 },
    },
  },
  {
    ...CLAUDE_5_BASE,
    model: 'claude-opus-5',
    displayName: 'Claude Opus 5',
    // The research states 128K output only for the four 5.5-generation models.
    maxOutput: null,
    forcedToolChoice: false,
    thinking: { on: 'adaptive', offMode: 'disabled', efforts: EFFORTS_BASE, defaultEffort: 'high' },
    pricing: { inputPerM: 5, outputPerM: 25, cacheReadPerM: 0.5, cacheWrite5mPerM: 6.25, cacheWrite1hPerM: 10 },
    unverified: ['contextWindow', 'maxOutput', 'forcedToolChoice', 'efforts'],
  },
  {
    ...CLAUDE_5_BASE,
    model: 'claude-sonnet-5',
    displayName: 'Claude Sonnet 5',
    maxOutput: null,
    forcedToolChoice: false,
    thinking: { on: 'adaptive', offMode: 'disabled', efforts: EFFORTS_BASE, defaultEffort: 'high' },
    pricing: { inputPerM: 2, outputPerM: 10, cacheReadPerM: 0.2, cacheWrite5mPerM: 2.5, cacheWrite1hPerM: 4 },
    unverified: ['contextWindow', 'maxOutput', 'forcedToolChoice', 'efforts'],
  },
];
