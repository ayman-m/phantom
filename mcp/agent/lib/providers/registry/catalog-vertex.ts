/**
 * Curated Gemini catalog (provider "vertex": Vertex AI and the Gemini API
 * share these ids).
 *
 * Vertex has no usable model list, so this table is authoritative for what
 * exists; the Gemini API list (when a key is configured) only enriches limits.
 *
 * Context windows are the values chat has always budgeted with, so history
 * trimming does not change: Gemini 3.x at 1M, Gemini 2.5 Pro at 2M, the 2.5
 * Flash models at 1M. Prices are the ones the cost table carried (Vertex
 * public pricing page, 2026-05); the 2026-10-13 research covered only Claude
 * and OpenAI, so they are not re-dated. Models with no price here (3.7 Flash,
 * 3.5 Flash) are unpriced rather than billed at a guess. 3.8 Flash carries its
 * introductory price (checked 2026-10-18) with an end date.
 *
 * Erasable TypeScript only.
 */

import type { CuratedModel, ModelPricing } from './types.ts';

const CHAT_DEFAULTS = {
  provider: 'vertex',
  kind: 'chat',
  tokenizerFactor: 1,
  tools: true,
  // Function calling mode ANY.
  forcedToolChoice: true,
  maxOutput: 65_536,
} as const;

const GEMINI_THINKING = { on: 'gemini', offMode: 'omit' } as const;

/** Vertex public pricing, as the cost table carried it (cached input at 25%). */
function priced(inputPerM: number, outputPerM: number): ModelPricing {
  return { inputPerM, outputPerM, cacheReadPerM: inputPerM * 0.25 };
}

const PRICING_DATE = '2026-05';

export const VERTEX_CATALOG: readonly CuratedModel[] = [
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-3.8-flash',
    displayName: 'Gemini 3.8 Flash',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: priced(0.75, 3.75),
    pricingVerified: '2026-10-18',
    pricingValidUntil: '2026-12-31',
    pricingNote:
      'Introductory price of $0.75 input and $3.75 output per million tokens through 2026-12-31; from 2027-01-01 the price is $1.50 and $7.50, and until the catalog carries that price the cost is reported as unpriced.',
    lifecycle: { stage: 'ga' },
    unverified: ['contextWindow', 'maxOutput'],
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-3.7-flash',
    displayName: 'Gemini 3.7 Flash',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'ga' },
    unverified: ['maxOutput', 'pricing'],
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-3.5-flash',
    displayName: 'Gemini 3.5 Flash',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'ga' },
    unverified: ['maxOutput', 'pricing'],
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-3.1-pro-preview',
    displayName: 'Gemini 3.1 Pro',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: priced(2.5, 12.0),
    pricingVerified: PRICING_DATE,
    lifecycle: { stage: 'preview' },
    recommended: true,
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-3.0-pro',
    displayName: 'Gemini 3.0 Pro',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: priced(2.0, 10.0),
    pricingVerified: PRICING_DATE,
    lifecycle: { stage: 'ga' },
    unverified: ['maxOutput'],
  },
  // The Gemini 2.5 family is on Google's retirement schedule (search summaries
  // say not before 2026-10-16; no official table was readable). Marked
  // deprecated without a retirement date, so nothing hides on a guessed day.
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-2.5-pro',
    displayName: 'Gemini 2.5 Pro',
    contextWindow: 2_000_000,
    thinking: GEMINI_THINKING,
    pricing: priced(1.25, 5.0),
    pricingVerified: PRICING_DATE,
    lifecycle: { stage: 'deprecated' },
    unverified: ['maxOutput', 'retiresAt'],
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-2.5-flash',
    displayName: 'Gemini 2.5 Flash',
    contextWindow: 1_000_000,
    thinking: GEMINI_THINKING,
    pricing: priced(0.075, 0.3),
    pricingVerified: PRICING_DATE,
    lifecycle: { stage: 'deprecated' },
    unverified: ['maxOutput', 'retiresAt'],
  },
  {
    ...CHAT_DEFAULTS,
    model: 'gemini-2.5-flash-lite',
    displayName: 'Gemini 2.5 Flash Lite',
    contextWindow: 1_000_000,
    // The picker has always shown this model without thinking.
    thinking: { on: 'none', offMode: 'omit' },
    pricing: priced(0.0375, 0.15),
    pricingVerified: PRICING_DATE,
    lifecycle: { stage: 'deprecated' },
    unverified: ['maxOutput', 'retiresAt'],
  },

  // Non-chat models. They are listed so /models shows them; chat cannot run on them.
  {
    provider: 'vertex',
    model: 'gemini-embedding-001',
    displayName: 'Gemini Embedding',
    kind: 'embedding',
    contextWindow: 8_192,
    maxOutput: null,
    tokenizerFactor: 1,
    tools: false,
    forcedToolChoice: false,
    thinking: { on: 'none', offMode: 'omit' },
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'ga' },
  },
  {
    provider: 'vertex',
    model: 'text-embedding-005',
    displayName: 'text-embedding-005',
    kind: 'embedding',
    contextWindow: 2_048,
    maxOutput: null,
    tokenizerFactor: 1,
    tools: false,
    forcedToolChoice: false,
    thinking: { on: 'none', offMode: 'omit' },
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'ga' },
  },
  {
    provider: 'vertex',
    model: 'imagen-4.0-generate-preview',
    displayName: 'Imagen 4',
    kind: 'image',
    contextWindow: 0,
    maxOutput: null,
    tokenizerFactor: 1,
    tools: false,
    forcedToolChoice: false,
    thinking: { on: 'none', offMode: 'omit' },
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'preview' },
  },
  {
    provider: 'vertex',
    model: 'imagen-3.0-generate-002',
    displayName: 'Imagen 3',
    kind: 'image',
    contextWindow: 0,
    maxOutput: null,
    tokenizerFactor: 1,
    tools: false,
    forcedToolChoice: false,
    thinking: { on: 'none', offMode: 'omit' },
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'ga' },
  },
  {
    provider: 'vertex',
    model: 'chirp-3-hd',
    displayName: 'Chirp 3 HD (TTS)',
    kind: 'voice',
    contextWindow: 0,
    maxOutput: null,
    tokenizerFactor: 1,
    tools: false,
    forcedToolChoice: false,
    thinking: { on: 'none', offMode: 'omit' },
    pricing: null,
    pricingVerified: null,
    lifecycle: { stage: 'preview' },
  },
];
