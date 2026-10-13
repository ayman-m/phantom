/**
 * The body of GET /api/agent/models, as a function of injected dependencies so
 * the route file stays a one-line wrapper (a Next route file may export only
 * its handlers, and cannot be loaded by a plain Node test).
 *
 * The response is a bare JSON array. Each element keeps the fields the UI has
 * always read (`provider`, `model`, `displayName`, `kind`, `contextWindow`,
 * `supportsThinking`, `supportsTools`, `launchStage`, `interactionPatterns`)
 * and adds the registry's: `ref`, `availability`, `selectable`, `reason`,
 * `pricing`, `lifecycle`, `liveSeenAt`, `source`, `isDefault`.
 *
 * Gemini credentials come from the runtime config (they can live in the
 * environment as well as the store); the other providers' come from the
 * ProviderStore reader. A provider with no credentials contributes its curated
 * rows as `not_configured`. `listRegistryEntries` is the one place that builds
 * that credential map, so what the chat route resolves a model against and
 * what this route serves cannot disagree about which providers are configured.
 *
 * `isDefault` marks the model chat uses when nothing else is chosen: the
 * install's `defaultModel` setting when its provider is configured, else the
 * derived default. `defaultSource` on that one row says which ('default' or
 * 'derived'); it is null on every other row.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import type { ProviderCreds, ProviderId } from '../types.ts';
import { describeInstallDefault } from '../model-resolution.ts';
import { pricingExpired } from './pricing.ts';
import type { ModelRegistry } from './registry.ts';
import type { ModelEntry, ModelKind, ModelPricing, ThinkingRules, UnverifiedFact } from './types.ts';

export interface GeminiRuntimeConfig {
  GEMINI_API_KEY?: string;
  GOOGLE_APPLICATION_CREDENTIALS?: string;
}

export interface ServeModelsDeps {
  registry: ModelRegistry;
  runtime: GeminiRuntimeConfig;
  resolveCreds: (provider: ProviderId) => Promise<ProviderCreds | null>;
  /** The effective `defaultModel` setting; undefined when it could not be read. */
  installDefault?: string;
  includeRetired?: boolean;
  now?: () => number;
}

export interface ApiModel {
  provider: ProviderId;
  model: string;
  ref: string;
  displayName: string;
  kind: ModelKind;
  /** 0 when unknown. */
  contextWindow: number;
  maxOutput: number | null;
  maxInput: number | null;
  tokenizerFactor: number;
  supportsThinking: boolean;
  supportsTools: boolean;
  forcedToolChoice: boolean;
  thinking: ThinkingRules;
  interactionPatterns: Array<'streaming_api' | 'async_job'>;
  launchStage: 'GA' | 'PUBLIC_PREVIEW' | 'DEPRECATED' | 'RETIRED';
  availability: ModelEntry['availability'];
  selectable: boolean;
  reason: string | null;
  pricing: ModelPricing | null;
  /** The pricing is known and still valid. */
  priced: boolean;
  pricingVerified: string | null;
  pricingValidUntil: string | null;
  pricingNote: string | null;
  lifecycle: ModelEntry['lifecycle'];
  liveSeenAt: string | null;
  source: ModelEntry['source'];
  providerState: ModelEntry['providerState'];
  refreshError: string | null;
  isDefault: boolean;
  /** On the default row: whether the install's setting or the derived model serves. */
  defaultSource: 'default' | 'derived' | null;
  recommended: boolean;
  unverified: readonly UnverifiedFact[];
}

const LAUNCH_STAGE = {
  ga: 'GA',
  preview: 'PUBLIC_PREVIEW',
  deprecated: 'DEPRECATED',
  retired: 'RETIRED',
} as const;

export function toApiModel(
  entry: ModelEntry,
  def: { ref: string | null; source: 'default' | 'derived' | 'none' },
  now: number,
): ApiModel {
  const isDefault = def.ref !== null && entry.ref === def.ref;
  return {
    provider: entry.provider,
    model: entry.model,
    ref: entry.ref,
    displayName: entry.displayName,
    kind: entry.kind,
    contextWindow: entry.contextWindow ?? 0,
    maxOutput: entry.maxOutput,
    maxInput: entry.maxInput ?? null,
    tokenizerFactor: entry.tokenizerFactor,
    supportsThinking: entry.thinking.on !== 'none',
    supportsTools: entry.tools,
    forcedToolChoice: entry.forcedToolChoice,
    thinking: entry.thinking,
    interactionPatterns: entry.kind === 'image' ? ['async_job'] : ['streaming_api'],
    launchStage: LAUNCH_STAGE[entry.lifecycle.stage],
    availability: entry.availability,
    selectable: entry.selectable,
    reason: entry.reason ?? null,
    pricing: entry.pricing,
    priced: entry.pricing !== null && !pricingExpired(entry, now),
    pricingVerified: entry.pricingVerified,
    pricingValidUntil: entry.pricingValidUntil ?? null,
    pricingNote: entry.pricingNote ?? null,
    lifecycle: entry.lifecycle,
    liveSeenAt: entry.liveSeenAt ?? null,
    source: entry.source,
    providerState: entry.providerState,
    refreshError: entry.refreshError ?? null,
    isDefault,
    defaultSource: isDefault && def.source !== 'none' ? def.source : null,
    recommended: Boolean(entry.recommended),
    unverified: entry.unverified,
  };
}

/** The registry's merged entries for the credentials this install has. */
export async function listRegistryEntries(
  deps: Pick<ServeModelsDeps, 'registry' | 'runtime' | 'resolveCreds' | 'includeRetired'>,
): Promise<ModelEntry[]> {
  const gemini: ProviderCreds = {
    apiKey: deps.runtime.GEMINI_API_KEY?.trim() || undefined,
    serviceAccountJson: deps.runtime.GOOGLE_APPLICATION_CREDENTIALS?.trim() || undefined,
  };
  const [anthropic, openai] = await Promise.all([
    deps.resolveCreds('anthropic'),
    deps.resolveCreds('openai'),
  ]);
  return await deps.registry.list({
    creds: { vertex: gemini, anthropic, openai },
    includeRetired: deps.includeRetired,
  });
}

export async function serveModels(deps: ServeModelsDeps): Promise<ApiModel[]> {
  // Judge the default against every entry, retired ones included, so a default
  // that names a retired model is reported as such rather than as unknown;
  // hide the retired rows afterwards, as the registry does.
  const all = await listRegistryEntries({ ...deps, includeRetired: true });
  const def = describeInstallDefault(deps.installDefault, all);
  const now = (deps.now ?? Date.now)();
  return all
    .filter((e) => deps.includeRetired || e.availability !== 'retired')
    .map((e) => toApiModel(e, def, now));
}
