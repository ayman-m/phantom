/**
 * Turn cost rows: how one model call becomes a `chat_turn_cost` audit row, and
 * how a set of those rows is read back and summed.
 *
 * One module owns both directions so the chat route (which writes the rows and
 * answers `/cost`), the `/observability/cost` page and the cost-warn hook all
 * agree on what a row means.
 *
 * Writing. `buildTurnCostMetadata` prices a call from its `NeutralUsage` with
 * the registry's price for the exact `provider/model` (never a bare id, which
 * could belong to two providers). A model with no known price, an expired
 * promotional price, or a usage shape the price table cannot cover is
 * **unpriced**: `priced` is false and `cost_usd` is `null`. A dollar figure is
 * never 0 or NaN for "unknown".
 *
 * Reading. Rows written before v1.0.5 have none of the newer fields. Every
 * reader here treats a missing `provider` as `vertex` (every earlier row was a
 * Gemini call), a missing `model_ref` as `<provider>/<model>`, a missing
 * `priced` as priced when `cost_usd` is a number, and missing token counts as 0.
 *
 * Reasoning tokens are already inside `output_tokens` (they are billed as
 * output). They are recorded so the cost page can show them, never added to the
 * bill a second time.
 *
 * Imported by client components, so no Node-only imports. Erasable TypeScript
 * only, with relative `.ts` imports, so unit tests load it with Node type
 * stripping.
 */

import { computeTurnCostUsd, type PricedEntry } from './providers/registry/pricing.ts';
import { lookupModelFacts } from './providers/registry/lookup.ts';
import type { NeutralUsage, ProviderId } from './providers/types.ts';
import { formatUsd } from './model-pricing.ts';

/** The provider a row without a `provider` field belongs to. */
export const LEGACY_ROW_PROVIDER: ProviderId = 'vertex';

export type CallKind = 'initial' | 'followup' | 'budget_summary';

/** What the chat route keeps from one recorded call. `usd` is null when unpriced. */
export interface CallCost {
  provider: ProviderId;
  modelRef: string;
  priced: boolean;
  usd: number | null;
  inputTokens: number;
  cachedTokens: number;
  cacheWriteTokens: number;
  cacheWrite1hTokens: number;
  reasoningTokens: number;
  outputTokens: number;
}

export interface TurnCostRecord {
  /** The `chat_turn_cost` audit metadata. */
  metadata: Record<string, unknown>;
  call: CallCost;
}

function tokens(n: unknown): number {
  return typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : 0;
}

function round6(n: number): number {
  return Number(n.toFixed(6));
}

/** Facts for the exact `provider/model`; null when the registry does not know it. */
function factsFor(provider: ProviderId, model: string): (PricedEntry & { pricingVerified: string | null }) | null {
  return lookupModelFacts(`${provider}/${model}`);
}

/**
 * Build the audit row for one model call from its normalized usage.
 *
 * The legacy fields keep their meaning (`input_tokens` is the whole prompt,
 * `cached_input_tokens` the cache read, `uncached_input_tokens` is input minus
 * the cache read, `model` the bare id), so a Gemini call writes the numbers it
 * always did. The newer fields sit beside them.
 */
export function buildTurnCostMetadata(args: {
  usage: NeutralUsage;
  provider: ProviderId;
  model: string;
  callKind: CallKind;
  requestId?: string;
  finish?: string;
  now?: number;
}): TurnCostRecord {
  const { usage, provider, model } = args;
  const inputTokens = tokens(usage.inputTotal);
  const cachedTokens = tokens(usage.cacheRead);
  const cacheWriteTokens = tokens(usage.cacheWrite);
  const cacheWrite1hTokens = Math.min(tokens(usage.cacheWrite1h), cacheWriteTokens);
  const reasoningTokens = tokens(usage.reasoning);
  const outputTokens = tokens(usage.output);
  const modelRef = `${provider}/${model}`;

  const facts = factsFor(provider, model);
  const cost = computeTurnCostUsd(usage, facts ?? { pricing: null }, { now: args.now });

  const metadata: Record<string, unknown> = {
    call_kind: args.callKind,
    input_tokens: inputTokens,
    cached_input_tokens: cachedTokens,
    output_tokens: outputTokens,
    uncached_input_tokens: Math.max(0, inputTokens - cachedTokens),
    cache_write_tokens: cacheWriteTokens,
    cache_write_1h_tokens: cacheWrite1hTokens,
    reasoning_tokens: reasoningTokens,
    priced: cost.priced,
    cost_usd: cost.priced ? round6(cost.usd) : null,
    cost_components: cost.priced
      ? {
          input_usd: round6(cost.components.inputUsd),
          cached_input_usd: round6(cost.components.cacheReadUsd),
          cache_write_usd: round6(cost.components.cacheWriteUsd),
          output_usd: round6(cost.components.outputUsd),
          uncached_hypothetical_input_usd: round6(cost.components.uncachedHypotheticalInputUsd),
          cached_savings_usd: round6(cost.components.cachedSavingsUsd),
        }
      : null,
    long_context: cost.priced ? cost.longContext : false,
    pricing_verified: facts?.pricingVerified ?? null,
    model,
    provider,
    model_ref: modelRef,
  };
  if (!cost.priced) metadata.unpriced_reason = facts ? cost.reason : 'unknown_model';
  if (args.requestId) metadata.request_id = args.requestId;
  if (args.finish) metadata.finish = args.finish;

  return {
    metadata,
    call: {
      provider,
      modelRef,
      priced: cost.priced,
      usd: cost.priced ? cost.usd : null,
      inputTokens,
      cachedTokens,
      cacheWriteTokens,
      cacheWrite1hTokens,
      reasoningTokens,
      outputTokens,
    },
  };
}

/**
 * What a cache hit saved, from the model's own prices: the cache-read tokens
 * billed at the cache-read rate instead of the input rate. Null when the model
 * is unpriced (no figure is better than a guessed one). Works the same for any
 * provider; cache-write overhead is not netted out here (the cost row's
 * `cached_savings_usd` does that).
 */
export function cacheReadSavings(args: {
  usage: NeutralUsage;
  provider: ProviderId;
  model: string;
  now?: number;
}): { usd: number; tokensEquivalent: number } | null {
  const facts = factsFor(args.provider, args.model);
  const cost = computeTurnCostUsd(args.usage, facts ?? { pricing: null }, { now: args.now });
  if (!cost.priced || !facts?.pricing) return null;
  const pricing = facts.pricing;
  const cacheRead = tokens(args.usage.cacheRead);
  const mult = cost.longContext && pricing.longContext ? pricing.longContext.inputMult : 1;
  const usd = (cacheRead / 1_000_000) * (pricing.inputPerM - pricing.cacheReadPerM) * mult;
  const tokensEquivalent =
    pricing.inputPerM > 0 ? Math.floor(cacheRead * (1 - pricing.cacheReadPerM / pricing.inputPerM)) : 0;
  return { usd: Math.max(0, round6(usd)), tokensEquivalent: Math.max(0, tokensEquivalent) };
}

// ─── Per-turn tally ────────────────────────────────────────────────────────

/** Running total over the model calls of one turn. */
export interface TurnTally {
  /** Sum over the priced calls only. */
  pricedUsd: number;
  pricedCalls: number;
  unpricedCalls: number;
  input: number;
  cached: number;
  cacheWrite: number;
  reasoning: number;
  output: number;
}

export function newTurnTally(): TurnTally {
  return { pricedUsd: 0, pricedCalls: 0, unpricedCalls: 0, input: 0, cached: 0, cacheWrite: 0, reasoning: 0, output: 0 };
}

export function addCallToTally(tally: TurnTally, call: CallCost): void {
  if (call.priced && call.usd !== null) {
    tally.pricedUsd += call.usd;
    tally.pricedCalls += 1;
  } else {
    tally.unpricedCalls += 1;
  }
  tally.input += call.inputTokens;
  tally.cached += call.cachedTokens;
  tally.cacheWrite += call.cacheWriteTokens;
  tally.reasoning += call.reasoningTokens;
  tally.output += call.outputTokens;
}

/**
 * The turn-level `turn_cost` summary. `cost_usd` is the sum over the priced
 * calls, or null when no call was priced. `priced` is false as soon as any
 * call was not, so a partial figure is never mistaken for a full one.
 */
export function turnCostSummary(
  tally: TurnTally,
): {
  cost_usd: number | null;
  priced: boolean;
  unpriced_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  output_tokens: number;
} {
  return {
    cost_usd: tally.pricedCalls > 0 ? round6(tally.pricedUsd) : null,
    priced: tally.unpricedCalls === 0 && tally.pricedCalls > 0,
    unpriced_calls: tally.unpricedCalls,
    input_tokens: tally.input,
    cached_input_tokens: tally.cached,
    cache_write_tokens: tally.cacheWrite,
    reasoning_tokens: tally.reasoning,
    output_tokens: tally.output,
  };
}

// ─── Reading rows ──────────────────────────────────────────────────────────

export interface CostRowLike {
  metadata?: Record<string, unknown> | null;
}

/** A row's fields after the old-row defaults. `usd` is null when the call was unpriced. */
export interface ReadCostRow {
  provider: string;
  model: string;
  modelRef: string;
  callKind: string;
  priced: boolean;
  usd: number | null;
  savingsUsd: number;
  input: number;
  cached: number;
  cacheWrite: number;
  cacheWrite1h: number;
  reasoning: number;
  output: number;
}

function text(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v.trim() : null;
}

export function rowProvider(meta: Record<string, unknown>): string {
  return text(meta['provider']) ?? LEGACY_ROW_PROVIDER;
}

export function readCostRow(row: CostRowLike): ReadCostRow {
  const m: Record<string, unknown> = row?.metadata && typeof row.metadata === 'object' ? row.metadata : {};
  const provider = rowProvider(m);
  const model = text(m['model']) ?? 'unknown';
  const modelRef = text(m['model_ref']) ?? `${provider}/${model}`;
  const cost = m['cost_usd'];
  const usd = typeof cost === 'number' && Number.isFinite(cost) ? cost : null;
  // `priced: false` is explicit on new rows; an old row is priced when it has a figure.
  const priced = m['priced'] === false ? false : usd !== null;
  const components = m['cost_components'];
  const savings =
    components && typeof components === 'object'
      ? (components as Record<string, unknown>)['cached_savings_usd']
      : undefined;
  return {
    provider,
    model,
    modelRef,
    callKind: text(m['call_kind']) ?? 'unknown',
    priced,
    usd: priced ? usd : null,
    savingsUsd: priced && typeof savings === 'number' && Number.isFinite(savings) ? savings : 0,
    input: tokens(m['input_tokens']),
    cached: tokens(m['cached_input_tokens']),
    cacheWrite: tokens(m['cache_write_tokens']),
    cacheWrite1h: tokens(m['cache_write_1h_tokens']),
    reasoning: tokens(m['reasoning_tokens']),
    output: tokens(m['output_tokens']),
  };
}

/** One group of rows. `usd` sums the priced calls only. */
export interface CostBucket {
  usd: number;
  calls: number;
  unpricedCalls: number;
  input: number;
  cached: number;
  cacheWrite: number;
  reasoning: number;
  output: number;
}

export function emptyBucket(): CostBucket {
  return { usd: 0, calls: 0, unpricedCalls: 0, input: 0, cached: 0, cacheWrite: 0, reasoning: 0, output: 0 };
}

export function addRowToBucket(bucket: CostBucket, row: ReadCostRow): void {
  bucket.calls += 1;
  if (row.priced && row.usd !== null) bucket.usd += row.usd;
  else bucket.unpricedCalls += 1;
  bucket.input += row.input;
  bucket.cached += row.cached;
  bucket.cacheWrite += row.cacheWrite;
  bucket.reasoning += row.reasoning;
  bucket.output += row.output;
}

export interface CostTotals extends CostBucket {
  savings: number;
  byProvider: Record<string, CostBucket>;
  byModelRef: Record<string, CostBucket>;
}

/** Sum a set of `chat_turn_cost` rows. Never throws on a malformed row. */
export function sumCostRows(rows: readonly CostRowLike[] | null | undefined): CostTotals {
  const out: CostTotals = { ...emptyBucket(), savings: 0, byProvider: {}, byModelRef: {} };
  for (const raw of rows ?? []) {
    const row = readCostRow(raw);
    addRowToBucket(out, row);
    out.savings += row.savingsUsd;
    addRowToBucket((out.byProvider[row.provider] ??= emptyBucket()), row);
    addRowToBucket((out.byModelRef[row.modelRef] ??= emptyBucket()), row);
  }
  return out;
}

/** The rows of an `/api/v1/audit` response, which is `{events, count, total}`. */
export function auditResponseRows(resp: unknown): CostRowLike[] {
  if (!resp || typeof resp !== 'object') return [];
  const events = (resp as { events?: unknown }).events;
  return Array.isArray(events) ? (events as CostRowLike[]) : [];
}

// ─── The /cost chat command ───────────────────────────────────────────────

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

/** "$1.23", "$1.23 + 2 unpriced calls", "unpriced (3 calls)" or "$0" for an empty window. */
export function describeBucketCost(b: Pick<CostBucket, 'usd' | 'calls' | 'unpricedCalls'>): string {
  if (b.calls === 0) return formatUsd(0);
  if (b.unpricedCalls === b.calls) return `unpriced (${plural(b.calls, 'call')}, no known price)`;
  if (b.unpricedCalls > 0) return `${formatUsd(b.usd)} + ${plural(b.unpricedCalls, 'unpriced call')}`;
  return formatUsd(b.usd);
}

function windowLines(title: string, t: CostTotals, suffix: string): string[] {
  const writes = t.cacheWrite > 0 ? `, ${t.cacheWrite.toLocaleString()} written to cache` : '';
  const reasoning = t.reasoning > 0 ? ` (${t.reasoning.toLocaleString()} reasoning)` : '';
  return [
    `**${title}** (${plural(t.calls, 'call')}${suffix}):`,
    `  • Input tokens: ${t.input.toLocaleString()} (${t.cached.toLocaleString()} cached${writes})`,
    `  • Output tokens: ${t.output.toLocaleString()}${reasoning}`,
    `  • Total: **${describeBucketCost(t)}**${t.savings > 0 ? ` (saved ${formatUsd(t.savings)} via prompt caching)` : ''}`,
  ];
}

/**
 * The `/cost` reply: this session and today (UTC), with today broken down by
 * provider and by model when more than one is in play. Rows without the newer
 * fields read as Gemini calls; unpriced calls are counted, never billed at $0.
 */
export function renderCostSummary(session: CostTotals, today: CostTotals): string {
  const lines: string[] = [
    '**Cost summary**',
    '',
    ...windowLines('This session', session, ''),
    '',
    ...windowLines('Today (UTC)', today, ' across all sessions'),
  ];
  const byDesc = (a: [string, CostBucket], b: [string, CostBucket]) => b[1].usd - a[1].usd;
  const providers = Object.entries(today.byProvider).sort(byDesc);
  if (providers.length > 1) {
    lines.push('', '**Today by provider:**');
    for (const [name, b] of providers) lines.push(`  • \`${name}\`: ${describeBucketCost(b)} (${plural(b.calls, 'call')})`);
  }
  const models = Object.entries(today.byModelRef).sort(byDesc);
  if (models.length > 1) {
    lines.push('', '**Today by model:**');
    for (const [ref, b] of models) lines.push(`  • \`${ref}\`: ${describeBucketCost(b)} (${plural(b.calls, 'call')})`);
  }
  lines.push(
    '',
    '_Pricing source: the per-model rates on [/models](/models); a call to a model with no known price is shown as unpriced and left out of the totals. Per-call audit rows in [/observability/events](/observability/events) (filter `action:chat_turn_cost`). Full rollups in [/observability/cost](/observability/cost)._',
  );
  return lines.join('\n');
}
