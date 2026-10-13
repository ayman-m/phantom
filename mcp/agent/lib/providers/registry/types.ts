/**
 * Model registry types.
 *
 * `CuratedModel` is what the catalogs state. `ModelEntry` is what
 * `registry.list()` serves: a curated row merged with whatever the provider's
 * live list said, plus the computed availability.
 *
 * Erasable TypeScript only; the one import is type-only.
 */

import type { ProviderId } from '../types.ts';

export type ModelKind = 'chat' | 'embedding' | 'image' | 'voice';

/** How the model thinks when asked to. */
export type ThinkingOn = 'none' | 'gemini' | 'adaptive' | 'enabled_budget' | 'reasoning';

/**
 * How "thinking off" is requested.
 *   omit          send no thinking configuration
 *   disabled      send an explicit disable
 *   between_tools no up-front thinking, thinking only between tool calls
 *   low_effort    the model cannot be switched off; use its lowest effort
 *   none_effort   reasoning effort "none"
 */
export type OffMode = 'omit' | 'disabled' | 'between_tools' | 'low_effort' | 'none_effort';

export interface ThinkingRules {
  on: ThinkingOn;
  offMode: OffMode;
  /** Effort levels the model accepts, when the provider has the concept. */
  efforts?: readonly string[];
  defaultEffort?: string;
}

/**
 * A prompt longer than `aboveInputTokens` (strictly) is billed at multiples of
 * the base rates for the whole request: `inputMult` on uncached input, cache
 * reads and cache writes; `outputMult` on output.
 */
export interface LongContextTier {
  aboveInputTokens: number;
  inputMult: number;
  outputMult: number;
}

/** USD per million tokens. */
export interface ModelPricing {
  inputPerM: number;
  outputPerM: number;
  cacheReadPerM: number;
  /** Price of a cache write. Providers with a single write tier state it here. */
  cacheWrite5mPerM?: number;
  cacheWrite1hPerM?: number;
  longContext?: LongContextTier;
}

export type LifecycleStage = 'ga' | 'preview' | 'deprecated' | 'retired';

export interface Lifecycle {
  stage: LifecycleStage;
  /** ISO date or timestamp. */
  retiresAt?: string;
}

/**
 * Facts the catalogs could not confirm from an official source. Listed per
 * entry so nothing unverified passes as settled.
 */
export type UnverifiedFact =
  | 'contextWindow'
  | 'maxOutput'
  | 'maxInput'
  | 'efforts'
  | 'defaultEffort'
  | 'offMode'
  | 'forcedToolChoice'
  | 'pricing'
  | 'retiresAt';

export interface CuratedModel {
  provider: ProviderId;
  model: string;
  displayName: string;
  kind: ModelKind;
  /** Null when no official source states it; callers then use the documented default cap. */
  contextWindow: number | null;
  maxOutput: number | null;
  /** Largest accepted prompt when below the window (e.g. 922K inside a 1.05M window). */
  maxInput?: number;
  /** Tokens per character relative to the 1.0 baseline: 1.3 for the newer Claude tokenizer. */
  tokenizerFactor: number;
  tools: boolean;
  forcedToolChoice: boolean;
  thinking: ThinkingRules;
  /** Null: the cost of a call is unknown, never guessed. */
  pricing: ModelPricing | null;
  /** The date the pricing was last checked against the vendor's page. */
  pricingVerified: string | null;
  /** Pricing stops being valid after this date (promotional rates). */
  pricingValidUntil?: string;
  pricingNote?: string;
  lifecycle: Lifecycle;
  /** The model a fresh install of this provider starts on. One per provider. */
  recommended?: boolean;
  unverified?: readonly UnverifiedFact[];
}

export type Availability =
  | 'available'
  | 'unavailable'
  | 'unverified'
  | 'unpriced'
  | 'deprecated'
  | 'retired'
  | 'not_configured';

/**
 * What the provider's live list told us.
 *   not_configured  no credential for this provider
 *   unchecked       configured, but the provider has no usable list (Vertex with a service account only)
 *   live            a list fetched within the TTL
 *   stale           the last good list, kept after a failed refresh (up to 24 h)
 *   offline         configured, a list exists, but none could be fetched
 */
export type ProviderState = 'not_configured' | 'unchecked' | 'live' | 'stale' | 'offline';

export type EntrySource = 'live' | 'curated' | 'live+curated';

export interface ModelEntry extends Omit<CuratedModel, 'unverified'> {
  /** "provider/model" */
  ref: string;
  availability: Availability;
  /** Chat can run on this model right now. */
  selectable: boolean;
  /** Why it is not selectable, or what to watch. Written for the operator. */
  reason?: string;
  /** When the live list that named this model was fetched. */
  liveSeenAt?: string;
  source: EntrySource;
  providerState: ProviderState;
  /** Set on an entry whose live list is stale or missing: the last refresh error. */
  refreshError?: string;
  unverified: readonly UnverifiedFact[];
}

export function refOf(provider: ProviderId, model: string): string {
  return `${provider}/${model}`;
}
