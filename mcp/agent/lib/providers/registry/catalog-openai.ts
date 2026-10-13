/**
 * Curated OpenAI catalog (provider "openai", Responses API).
 *
 * Source: the vendor's models, pricing, reasoning and prompt-caching pages,
 * read 2026-10-13 (the fetch tool summarised each page, so the table should be
 * rechecked at every release tag). The live list (`GET /v1/models`) carries
 * only ids and shutdown dates, so this table is authoritative for everything
 * else and the live list only filters it to what the key can see.
 *
 * Cache reads and cache writes are priced separately: reads at 0.1x input
 * (0.05x on gpt-6.1-sol), writes at 1.25x input, one write tier (30 minutes),
 * stated as `cacheWrite5mPerM`.
 *
 * Deliberately absent: the deprecated codex ids and older snapshots. A key
 * that can see them lists them as unverified and not selectable.
 *
 * Erasable TypeScript only.
 */

import type { CuratedModel, ModelPricing, ThinkingRules } from './types.ts';

const VERIFIED = '2026-10-13';

const BASE = {
  provider: 'openai',
  kind: 'chat',
  tokenizerFactor: 1,
  tools: true,
  // tool_choice "required".
  forcedToolChoice: true,
  pricingVerified: VERIFIED,
  lifecycle: { stage: 'ga' },
} as const;

function round(n: number): number {
  return Math.round(n * 1e6) / 1e6;
}

function pricing(
  input: number,
  cachedInput: number,
  output: number,
  longContext?: ModelPricing['longContext'],
): ModelPricing {
  return {
    inputPerM: input,
    outputPerM: output,
    cacheReadPerM: cachedInput,
    cacheWrite5mPerM: round(input * 1.25),
    ...(longContext ? { longContext } : {}),
  };
}

/** Prompts above 272K input tokens: twice the input and cache rates, 1.5x output. */
const LONG_272K = { aboveInputTokens: 272_000, inputMult: 2, outputMult: 1.5 } as const;

const REASONING_NO_NONE: ThinkingRules = {
  on: 'reasoning',
  // The model has no "none" effort: off means its lowest listed effort.
  offMode: 'low_effort',
  efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
  defaultEffort: 'medium',
};

const REASONING_WITH_NONE: ThinkingRules = {
  on: 'reasoning',
  offMode: 'none_effort',
  efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
  defaultEffort: 'medium',
};

export const OPENAI_CATALOG: readonly CuratedModel[] = [
  {
    ...BASE,
    model: 'gpt-6-astra',
    displayName: 'GPT-6 Astra',
    contextWindow: 1_050_000,
    maxInput: 922_000,
    maxOutput: 128_000,
    thinking: {
      ...REASONING_NO_NONE,
      // Only "no none" is stated for Astra; the upper levels are not.
      efforts: ['low', 'medium', 'high'],
    },
    pricing: pricing(10, 1, 50, LONG_272K),
    unverified: ['efforts', 'defaultEffort'],
  },
  {
    ...BASE,
    model: 'gpt-6.1-sol',
    displayName: 'GPT-6.1 Sol',
    contextWindow: 1_050_000,
    maxOutput: 128_000,
    thinking: REASONING_NO_NONE,
    pricing: pricing(2, 0.1, 10),
    unverified: ['defaultEffort'],
  },
  {
    ...BASE,
    model: 'gpt-6-sol',
    displayName: 'GPT-6 Sol',
    contextWindow: 1_050_000,
    maxOutput: 128_000,
    thinking: REASONING_WITH_NONE,
    pricing: pricing(2, 0.2, 10),
    recommended: true,
  },
  {
    ...BASE,
    model: 'gpt-6-luna',
    displayName: 'GPT-6 Luna',
    contextWindow: 1_050_000,
    maxInput: 922_000,
    maxOutput: 128_000,
    thinking: REASONING_WITH_NONE,
    // The vendor states the long-context tier for "Astra and Luna"; read here as gpt-6-luna.
    pricing: pricing(0.1, 0.01, 0.5, LONG_272K),
    pricingNote: 'The long-context tier is stated for "Astra and Luna" and read as gpt-6-luna.',
  },
  {
    ...BASE,
    model: 'gpt-5.6-sol',
    displayName: 'GPT-5.6 Sol',
    contextWindow: 1_050_000,
    maxOutput: 128_000,
    thinking: { on: 'reasoning', offMode: 'omit', defaultEffort: 'medium' },
    pricing: pricing(4, 0.4, 20),
    pricingValidUntil: '2026-11-21',
    pricingNote: 'Promotional price through 2026-11-21; after that date the cost is reported as unpriced.',
    unverified: ['efforts', 'offMode', 'defaultEffort'],
  },
  {
    ...BASE,
    model: 'gpt-5.6-terra',
    displayName: 'GPT-5.6 Terra',
    contextWindow: null,
    maxOutput: null,
    thinking: { on: 'reasoning', offMode: 'omit', defaultEffort: 'medium' },
    pricing: pricing(2, 0.2, 12),
    unverified: ['contextWindow', 'maxOutput', 'efforts', 'offMode', 'defaultEffort'],
  },
  {
    ...BASE,
    model: 'gpt-5.6-luna',
    displayName: 'GPT-5.6 Luna',
    contextWindow: null,
    maxOutput: null,
    thinking: { on: 'reasoning', offMode: 'omit', defaultEffort: 'medium' },
    pricing: pricing(0.2, 0.02, 1.2),
    unverified: ['contextWindow', 'maxOutput', 'efforts', 'offMode', 'defaultEffort'],
  },
];
