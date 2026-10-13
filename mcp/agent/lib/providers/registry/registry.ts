/**
 * The model registry: curated metadata merged with each provider's live list.
 *
 * Merge rules (`mergeProvider`, pure):
 *   - A live value wins for context window, output cap, input cap, thinking
 *     and effort capabilities, and lifecycle (retirement).
 *   - The curated table wins for pricing, how "thinking off" is requested
 *     (one exception: a model the live list says cannot be disabled is never
 *     asked to disable), and forced tool choice.
 *   - Live-only Anthropic models are selectable and unpriced; live-only OpenAI
 *     models are unverified and not selectable; live-only Gemini ids are
 *     ignored (the Gemini API list only enriches the limits of curated rows).
 *
 * Availability, in priority order: retired, not_configured, unavailable
 * (the key cannot see it), deprecated, unverified (no live proof), unpriced,
 * available. A retired model (past its retirement date) is hidden from
 * `list()` unless asked for; one within 30 days of retirement is
 * `deprecated`: shown with a badge, still selectable.
 *
 * Live lists are cached per provider for 10 minutes, keyed by a hash of the
 * credential (never the credential), the last good list is kept 24 hours, a
 * failure is remembered for a minute so a dead provider is not hammered, and
 * concurrent refreshes share one request. The cache is stale-while-revalidate:
 * once the 10 minutes have passed, the last good list is served at once and the
 * refresh runs in the background, so a chat turn does not wait on a vendor's
 * model list it already holds; only a call with no list at all (the first
 * after start-up, a changed credential) waits, bounded by the refresh
 * deadline. Each refresh writes an audit row through the injected sink. With
 * no live list at all, the curated rows are served as `unverified`,
 * selectable for Vertex and Anthropic.
 *
 * `selectable` also requires that this build can run the provider
 * (`dispatchable`); credentials alone do not make a model chat-capable.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { createHash } from 'node:crypto';
import { ProviderError, redactSecrets } from '../errors.ts';
import type { LiveCapabilities, LiveModel, ProviderCreds, ProviderId } from '../types.ts';
import { fetchLiveModels, type LiveFetchDeps } from './live.ts';
import { CURATED_CATALOG, PROVIDER_LABELS, PROVIDER_ORDER, publishModelFacts } from './lookup.ts';
import { pricingExpired } from './pricing.ts';
import {
  refOf,
  type Availability,
  type CuratedModel,
  type Lifecycle,
  type ModelEntry,
  type ProviderState,
  type ThinkingRules,
  type UnverifiedFact,
} from './types.ts';

export const LIVE_TTL_MS = 10 * 60_000;
export const LAST_GOOD_MS = 24 * 60 * 60_000;
export const FAILURE_BACKOFF_MS = 60_000;
export const DEPRECATION_WINDOW_MS = 30 * 24 * 60 * 60_000;
/** One live refresh (the name lookup and every page together) gets this long. */
export const REFRESH_DEADLINE_MS = 15_000;

/**
 * Providers whose models this build can run a chat turn on. Credentials make a
 * model listable; only a provider in this list makes it selectable. Each
 * provider is added here in the change that adds its adapter.
 */
export const DISPATCHABLE_PROVIDERS: readonly ProviderId[] = ['vertex', 'anthropic', 'openai'];

/* ─── Pure merge ────────────────────────────────────────────── */

export interface LiveSnapshot {
  state: 'live' | 'stale';
  /** Epoch ms of the fetch that produced the list. */
  at: number;
  models: readonly LiveModel[];
}

export interface MergeInput {
  provider: ProviderId;
  curated: readonly CuratedModel[];
  configured: boolean;
  /** The provider has a list endpoint we can call with these credentials. */
  hasLiveSource: boolean;
  live: LiveSnapshot | null;
  refreshError?: string;
  now: number;
  dispatchable: boolean;
}

function dateLabel(iso: string | undefined): string {
  return iso ? iso.slice(0, 10) : '';
}

export function mergeLifecycle(base: Lifecycle, live: LiveModel | undefined, now: number): Lifecycle {
  let stage = base.stage;
  const retiresAt = live?.retiresAt ?? base.retiresAt;
  if (live?.lifecycle === 'retired') stage = 'retired';
  else if (live?.lifecycle === 'deprecated' && stage !== 'retired') stage = 'deprecated';
  if (retiresAt) {
    const t = Date.parse(retiresAt);
    if (Number.isFinite(t)) {
      if (t <= now) stage = 'retired';
      else if (t - now <= DEPRECATION_WINDOW_MS && stage !== 'retired') stage = 'deprecated';
    }
  }
  return retiresAt ? { stage, retiresAt } : { stage };
}

export function mergeThinking(base: ThinkingRules, caps: LiveCapabilities | undefined): ThinkingRules {
  if (!caps) return base;
  let on = base.on;
  if (caps.thinkingAdaptive === true) on = 'adaptive';
  else if (caps.thinkingAdaptive === false && caps.thinkingEnabled === true) on = 'enabled_budget';
  else if (caps.thinkingAdaptive === false && caps.thinkingEnabled === false) on = 'none';
  // The curated off mode wins, except that a model the live list says cannot
  // be disabled must not be sent a disable (a 400).
  const offMode = base.offMode === 'disabled' && caps.thinkingDisabled === false ? 'low_effort' : base.offMode;
  const efforts = caps.efforts && caps.efforts.length > 0 ? caps.efforts : base.efforts;
  const defaultEffort = base.defaultEffort && efforts && !efforts.includes(base.defaultEffort) ? undefined : base.defaultEffort;
  const out: ThinkingRules = { on, offMode };
  if (efforts) out.efforts = efforts;
  if (defaultEffort) out.defaultEffort = defaultEffort;
  return out;
}

interface Decision {
  availability: Availability;
  selectable: boolean;
  reason?: string;
}

interface DecideInput {
  provider: ProviderId;
  configured: boolean;
  lifecycle: Lifecycle;
  priced: boolean;
  inLive: boolean;
  listed: boolean;
  liveOnly: boolean;
}

function decide(d: DecideInput): Decision {
  const label = PROVIDER_LABELS[d.provider];
  if (d.lifecycle.stage === 'retired') {
    const on = dateLabel(d.lifecycle.retiresAt);
    return { availability: 'retired', selectable: false, reason: on ? `Retired on ${on}.` : 'Retired.' };
  }
  if (!d.configured) {
    return {
      availability: 'not_configured',
      selectable: false,
      reason: `Add ${label} credentials on the Providers page to use this model.`,
    };
  }
  if (d.listed && !d.inLive && d.provider !== 'vertex') {
    return { availability: 'unavailable', selectable: false, reason: 'The configured API key cannot see this model.' };
  }
  if (d.liveOnly && d.provider === 'openai') {
    return {
      availability: 'unverified',
      selectable: false,
      reason: 'Listed by OpenAI but not in the built-in model table, so its capabilities are unknown.',
    };
  }
  if (d.lifecycle.stage === 'deprecated') {
    const on = dateLabel(d.lifecycle.retiresAt);
    return { availability: 'deprecated', selectable: true, reason: on ? `Deprecated; retires on ${on}.` : 'Deprecated.' };
  }
  if (!d.listed || (d.provider === 'vertex' && !d.inLive)) {
    if (d.provider === 'vertex') {
      return {
        availability: 'unverified',
        selectable: true,
        reason: 'Not checked against a live list. Use Verify on the model page to confirm it is enabled.',
      };
    }
    return {
      availability: 'unverified',
      selectable: d.provider !== 'openai',
      reason: `Could not reach ${label} to check this model.`,
    };
  }
  if (!d.priced) {
    return { availability: 'unpriced', selectable: true, reason: 'Cost is not tracked for this model.' };
  }
  return { availability: 'available', selectable: true };
}

function providerStateOf(m: MergeInput): ProviderState {
  if (!m.configured) return 'not_configured';
  if (m.live) return m.live.state;
  return m.hasLiveSource ? 'offline' : 'unchecked';
}

const NON_CHAT_OPENAI = /embedding|moderation|image|tts|whisper|transcribe|realtime|audio|live|dall-e|sora/i;
const CHAT_OPENAI = /^(gpt-|chatgpt|o\d)/i;

/** A live-only OpenAI id worth listing: a chat-looking id, none of the non-chat families. */
export function isOpenAiChatId(id: string): boolean {
  return CHAT_OPENAI.test(id) && !NON_CHAT_OPENAI.test(id);
}

function liveOnlyThinking(caps: LiveCapabilities | undefined): ThinkingRules {
  if (!caps) return { on: 'none', offMode: 'omit' };
  const on = caps.thinkingAdaptive === true ? 'adaptive' : caps.thinkingEnabled === true ? 'enabled_budget' : 'none';
  if (on === 'none') return { on, offMode: 'omit' };
  const rules: ThinkingRules = {
    on,
    // A disable the live list does not confirm is not sent.
    offMode: caps.thinkingDisabled === true ? 'disabled' : 'low_effort',
  };
  if (caps.efforts && caps.efforts.length > 0) rules.efforts = caps.efforts;
  return rules;
}

function withoutFacts(list: readonly UnverifiedFact[] | undefined, drop: UnverifiedFact[]): readonly UnverifiedFact[] {
  return (list ?? []).filter((f) => !drop.includes(f));
}

export function mergeProvider(m: MergeInput): ModelEntry[] {
  const state = providerStateOf(m);
  const listed = m.live !== null;
  const seenAt = m.live ? new Date(m.live.at).toISOString() : undefined;
  const liveById = new Map<string, LiveModel>();
  for (const l of m.live?.models ?? []) liveById.set(l.id, l);
  const refreshError = state === 'stale' || state === 'offline' ? m.refreshError : undefined;

  const finish = (
    base: Omit<ModelEntry, 'ref' | 'availability' | 'selectable' | 'reason' | 'providerState' | 'refreshError' | 'liveSeenAt' | 'source' | 'unverified'>,
    unverified: readonly UnverifiedFact[],
    d: Decision,
    inLive: boolean,
    liveOnly: boolean,
  ): ModelEntry => {
    let { selectable, reason } = d;
    if (selectable && base.kind !== 'chat') {
      selectable = false;
      reason = 'Not a chat model.';
    }
    if (selectable && !m.dispatchable) {
      selectable = false;
      reason = `Chat cannot run on ${PROVIDER_LABELS[m.provider]} models on this install.`;
    }
    const entry: ModelEntry = {
      ...base,
      ref: refOf(base.provider, base.model),
      availability: d.availability,
      selectable,
      source: liveOnly ? 'live' : inLive ? 'live+curated' : 'curated',
      providerState: state,
      unverified,
    };
    if (reason) entry.reason = reason;
    if (inLive && seenAt) entry.liveSeenAt = seenAt;
    if (refreshError) entry.refreshError = refreshError;
    return entry;
  };

  const out: ModelEntry[] = [];
  const curatedIds = new Set<string>();

  for (const c of m.curated) {
    curatedIds.add(c.model);
    const l = liveById.get(c.model);
    const lifecycle = mergeLifecycle(c.lifecycle, l, m.now);
    const { unverified, ...rest } = c;
    const dropped: UnverifiedFact[] = [];
    if (l?.contextWindow) dropped.push('contextWindow');
    if (l?.maxOutput) dropped.push('maxOutput');
    if (l?.maxInput) dropped.push('maxInput');
    if (l?.capabilities?.efforts?.length) dropped.push('efforts');
    if (l?.retiresAt) dropped.push('retiresAt');
    const maxInput = l?.maxInput ?? c.maxInput;
    const d = decide({
      provider: m.provider,
      configured: m.configured,
      lifecycle,
      priced: c.pricing !== null && !pricingExpired(c, m.now),
      inLive: l !== undefined,
      listed,
      liveOnly: false,
    });
    out.push(
      finish(
        {
          ...rest,
          contextWindow: l?.contextWindow ?? c.contextWindow,
          maxOutput: l?.maxOutput ?? c.maxOutput,
          ...(maxInput !== undefined ? { maxInput } : {}),
          thinking: mergeThinking(c.thinking, l?.capabilities),
          lifecycle,
        },
        withoutFacts(unverified, dropped),
        d,
        l !== undefined,
        false,
      ),
    );
  }

  // Live-only models.
  if (m.configured && m.live && (m.provider === 'anthropic' || m.provider === 'openai')) {
    const extras = m.live.models
      .filter((l) => !curatedIds.has(l.id) && (m.provider === 'anthropic' || isOpenAiChatId(l.id)))
      .sort((a, b) => b.id.localeCompare(a.id));
    for (const l of extras) {
      const lifecycle = mergeLifecycle({ stage: 'ga' }, l, m.now);
      const anthropic = m.provider === 'anthropic';
      const facts: UnverifiedFact[] = ['pricing', 'forcedToolChoice', 'offMode'];
      if (!l.contextWindow) facts.push('contextWindow');
      if (!l.maxOutput) facts.push('maxOutput');
      const d = decide({
        provider: m.provider,
        configured: true,
        lifecycle,
        priced: false,
        inLive: true,
        listed: true,
        liveOnly: true,
      });
      out.push(
        finish(
          {
            provider: m.provider,
            model: l.id,
            displayName: l.displayName ?? l.id,
            kind: 'chat',
            contextWindow: l.contextWindow ?? null,
            maxOutput: l.maxOutput ?? null,
            ...(l.maxInput ? { maxInput: l.maxInput } : {}),
            // Conservative for an unknown Claude: the larger factor shrinks the input budget.
            tokenizerFactor: anthropic ? 1.3 : 1,
            tools: anthropic,
            forcedToolChoice: false,
            thinking: anthropic ? liveOnlyThinking(l.capabilities) : { on: 'none', offMode: 'omit' },
            pricing: null,
            pricingVerified: null,
            lifecycle,
          },
          facts,
          d,
          true,
          true,
        ),
      );
    }
  }

  return out;
}

/* ─── Registry with live fetch, cache and audit ─────────────── */

export type AuditSink = (
  action: string,
  row: { target?: string; status?: 'success' | 'failure'; durationMs?: number; metadata: Record<string, unknown> },
) => void | Promise<void>;

export interface RegistryDeps extends LiveFetchDeps {
  now?: () => number;
  audit?: AuditSink;
  /** Defaults to `fetchLiveModels`; injectable for tests. */
  fetchLive?: typeof fetchLiveModels;
  catalog?: readonly CuratedModel[];
  dispatchable?: readonly ProviderId[];
  ttlMs?: number;
  lastGoodMs?: number;
  failureBackoffMs?: number;
  /** Overall deadline for one provider's refresh; default 15 s. */
  refreshDeadlineMs?: number;
  /** Publish merged facts for the synchronous lookups (default true). */
  publishFacts?: boolean;
}

export interface ListInput {
  /** Credentials per provider; null or absent means not configured. */
  creds: Partial<Record<ProviderId, ProviderCreds | null>>;
  /** Include retired models (hidden by default). */
  includeRetired?: boolean;
}

export interface ModelRegistry {
  list(input: ListInput): Promise<ModelEntry[]>;
  /** Resolves when no background refresh is running. Tests await it; callers need not. */
  idle(): Promise<void>;
  /** Drop cached live lists (one provider, or all). Call after credentials change. */
  bust(provider?: ProviderId): void;
}

export function isConfigured(provider: ProviderId, creds: ProviderCreds | null | undefined): boolean {
  if (!creds) return false;
  const key = creds.apiKey?.trim();
  if (provider === 'vertex') return Boolean(key || creds.serviceAccountJson?.trim());
  return Boolean(key);
}

function hasLiveSource(provider: ProviderId, creds: ProviderCreds): boolean {
  return provider !== 'vertex' || Boolean(creds.apiKey?.trim());
}

/** A hash of what identifies the credential; the credential itself never keys anything. */
export function credentialCacheKey(provider: ProviderId, creds: ProviderCreds): string {
  const parts = provider === 'vertex'
    ? [creds.apiKey ?? '']
    : [creds.apiKey ?? '', creds.baseUrl ?? '', creds.organization ?? '', creds.project ?? ''];
  return createHash('sha256').update(JSON.stringify([provider, ...parts])).digest('hex');
}

interface Slot {
  key: string;
  good?: { at: number; models: readonly LiveModel[] };
  failedAt?: number;
  error?: string;
  inflight?: Promise<void>;
}

/**
 * Run `work` with an overall deadline. The signal aborts every request the work
 * has in flight; the race also covers the host-name lookup, which cannot be
 * aborted. A late failure of the abandoned work is swallowed.
 */
async function withDeadline<T>(work: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new ProviderError({ kind: 'network', message: 'The provider did not answer in time.', retryable: true }));
    }, ms);
  });
  const running = work(controller.signal);
  running.catch(() => {});
  try {
    return await Promise.race([running, expired]);
  } finally {
    clearTimeout(timer);
  }
}

function safeMessage(err: unknown): string {
  if (err instanceof ProviderError) return err.message;
  return 'The model list could not be fetched.';
}

export function createModelRegistry(deps: RegistryDeps = {}): ModelRegistry {
  const now = deps.now ?? Date.now;
  const ttl = deps.ttlMs ?? LIVE_TTL_MS;
  const lastGoodMs = deps.lastGoodMs ?? LAST_GOOD_MS;
  const backoff = deps.failureBackoffMs ?? FAILURE_BACKOFF_MS;
  const deadline = deps.refreshDeadlineMs ?? REFRESH_DEADLINE_MS;
  const fetchLive = deps.fetchLive ?? fetchLiveModels;
  const catalog = deps.catalog ?? CURATED_CATALOG;
  const dispatchable = deps.dispatchable ?? DISPATCHABLE_PROVIDERS;
  const slots = new Map<ProviderId, Slot>();

  const audit = (action: string, row: Parameters<AuditSink>[1]): void => {
    if (!deps.audit) return;
    try {
      void Promise.resolve(deps.audit(action, row)).catch(() => {});
    } catch {
      // Auditing never blocks or breaks a listing.
    }
  };

  async function refresh(provider: ProviderId, creds: ProviderCreds, slot: Slot): Promise<void> {
    const started = now();
    try {
      const models = await withDeadline((signal) => fetchLive(provider, creds, { ...deps, signal }), deadline);
      if (models === null) return;
      slot.good = { at: now(), models };
      slot.failedAt = undefined;
      slot.error = undefined;
      audit('provider_models_refreshed', {
        target: `provider:${provider}`,
        status: 'success',
        durationMs: Math.max(0, Math.round(now() - started)),
        metadata: { provider, model_count: models.length },
      });
    } catch (err) {
      slot.failedAt = now();
      slot.error = redactSecrets(safeMessage(err));
      audit('provider_models_refresh_failed', {
        target: `provider:${provider}`,
        status: 'failure',
        durationMs: Math.max(0, Math.round(now() - started)),
        metadata: {
          provider,
          error_kind: err instanceof ProviderError ? err.kind : 'unknown',
          ...(err instanceof ProviderError && err.status !== undefined ? { status: err.status } : {}),
          message: slot.error,
        },
      });
    }
  }

  /** Start a refresh unless one is already running; every caller shares it. */
  function startRefresh(provider: ProviderId, creds: ProviderCreds, slot: Slot): Promise<void> {
    slot.inflight ??= refresh(provider, creds, slot).finally(() => {
      slot.inflight = undefined;
    });
    return slot.inflight;
  }

  /**
   * The provider's live list, stale-while-revalidate:
   *
   *   - within the TTL: served as it is;
   *   - past the TTL with a last-good list still inside `lastGoodMs`: that list
   *     is served at once and one refresh runs in the background (shared by
   *     every caller, never started during the failure back-off), so a chat
   *     turn never waits on a vendor's model list it already has. The list is
   *     `live` unless a refresh failed since it was fetched, then `stale` with
   *     the error;
   *   - no usable list at all (first call, a different credential, the list
   *     aged out): the caller waits for the refresh, bounded by its deadline,
   *     unless the provider is in its failure back-off.
   */
  async function liveFor(
    provider: ProviderId,
    creds: ProviderCreds,
  ): Promise<{ live: LiveSnapshot | null; error?: string }> {
    if (!hasLiveSource(provider, creds)) return { live: null };
    const key = credentialCacheKey(provider, creds);
    let slot = slots.get(provider);
    if (!slot || slot.key !== key) {
      // A different credential: nothing from the old one may be served.
      slot = { key };
      slots.set(provider, slot);
    }
    const t = now();
    const good = slot.good;
    const age = good ? t - good.at : Infinity;
    const backingOff = slot.failedAt !== undefined && t - slot.failedAt < backoff;

    if (good && age < ttl) {
      return { live: { state: 'live', at: good.at, models: good.models } };
    }
    if (good && age < lastGoodMs) {
      if (!backingOff) void startRefresh(provider, creds, slot);
      const failedSince = slot.failedAt !== undefined;
      return {
        live: { state: failedSince ? 'stale' : 'live', at: good.at, models: good.models },
        error: failedSince ? slot.error : undefined,
      };
    }
    if (!backingOff) await startRefresh(provider, creds, slot);
    else if (slot.inflight) await slot.inflight;
    // The refresh may have produced a list; if not, the failure is reported.
    const latest = slot.good;
    if (latest && now() - latest.at < lastGoodMs) {
      return { live: { state: now() - latest.at < ttl ? 'live' : 'stale', at: latest.at, models: latest.models }, error: slot.error };
    }
    return { live: null, error: slot.error };
  }

  return {
    async list(input) {
      const t = now();
      const perProvider = await Promise.all(
        PROVIDER_ORDER.map(async (provider) => {
          const creds = input.creds[provider] ?? null;
          const configured = isConfigured(provider, creds);
          const source = configured && creds ? hasLiveSource(provider, creds) : false;
          const { live, error } = configured && creds ? await liveFor(provider, creds) : { live: null, error: undefined };
          return mergeProvider({
            provider,
            curated: catalog.filter((c) => c.provider === provider),
            configured,
            hasLiveSource: source,
            live,
            refreshError: error,
            now: t,
            dispatchable: dispatchable.includes(provider),
          });
        }),
      );
      const all = perProvider.flat();
      if (deps.publishFacts !== false) publishModelFacts(all);
      return input.includeRetired ? all : all.filter((e) => e.availability !== 'retired');
    },
    async idle() {
      // A refresh finishing can leave no new one behind (refreshes start from list()), but loop to be safe.
      while (true) {
        const running = [...slots.values()].map((slot) => slot.inflight).filter((p): p is Promise<void> => p !== undefined);
        if (running.length === 0) return;
        await Promise.all(running);
      }
    },
    bust(provider) {
      if (provider) slots.delete(provider);
      else slots.clear();
    },
  };
}

/* ─── Process-wide instance ─────────────────────────────────── */

let shared: ModelRegistry | null = null;
let sharedDeps: RegistryDeps = {};

/** Configure the shared registry's dependencies (audit sink, blocked hosts). Call before first use. */
export function configureModelRegistry(deps: RegistryDeps): void {
  sharedDeps = deps;
  shared = null;
}

export function getModelRegistry(): ModelRegistry {
  shared ??= createModelRegistry(sharedDeps);
  return shared;
}

/** Drop the shared registry's cached live lists. Called when provider credentials change. */
export function bustModelRegistryCache(provider?: ProviderId): void {
  shared?.bust(provider);
}
