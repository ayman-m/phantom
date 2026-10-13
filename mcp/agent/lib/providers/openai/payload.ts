/**
 * OpenAI Responses API request builder: neutral `ModelRequest` in, the JSON
 * body for `POST {base}/responses` out. Pure; nothing here touches the network.
 *
 * What the mapping guarantees:
 *   - `store: false` and `stream: true` always; the conversation is replayed in
 *     full on every call, nothing is kept server side;
 *   - the system prompt is `instructions` (omitted when blank);
 *   - history text is `message` items with plain string content;
 *   - an in-loop assistant turn is replayed through its native output items
 *     (`turn.raw`): reasoning items with `encrypted_content`, messages and
 *     `function_call` items, in order (see `replayItems`);
 *   - tool results are `function_call_output` items keyed by `call_id`, in
 *     order, followed by one user message per directive;
 *   - tools use the wire names of the tool-name codec (64-character cap); with
 *     no tools, none of `tools`, `tool_choice` and `parallel_tool_calls` is sent;
 *   - `temperature`, `top_p`, `truncation` and `service_tier` are never sent, so
 *     a context overflow is an error rather than a silent trim;
 *   - `max_output_tokens = min(registry maxOutput, cap)`; it bounds reasoning
 *     and visible output together;
 *   - `prompt_cache_key` is the SHA-256 of the session-derived `cacheKey`, so a
 *     raw session id never leaves the install.
 *
 * The model's reasoning rules (from the registry) decide `reasoning` and
 * `include`; see `resolveReasoning`.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { createHash } from 'node:crypto';
import type { ModelFacts } from '../registry/lookup.ts';
import { toPortableSchema } from '../schema.ts';
import { buildToolNameCodec, type ToolNameCodec } from '../tool-names.ts';
import type { ModelRequest, ProviderEvent, ToolResultItem, ToolSpec, TurnMessage } from '../types.ts';

/** The registry facts this builder reads. A model the registry does not know passes null. */
export type OpenAiRules = Pick<ModelFacts, 'maxOutput' | 'forcedToolChoice' | 'thinking'>;

export type OpenAiItem = Record<string, unknown>;

export interface OpenAiTool {
  type: 'function';
  name: string;
  description?: string;
  parameters: Record<string, unknown>;
  strict: false;
}

export interface BuiltOpenAiRequest {
  body: Record<string, unknown>;
  /** Observations the adapter reports through `onEvent`. */
  events: ProviderEvent[];
  codec: ToolNameCodec;
}

/** Output cap for a model whose maximum the registry does not state. */
export const UNKNOWN_MODEL_MAX_TOKENS = 32_000;

export const PLACEHOLDER_EMPTY_USER = '(no content)';

/** Lowest-first. `none` is deliberately absent: it is a distinct "no reasoning" mode, not a level. */
const EFFORT_LADDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'] as const;

const FALLBACK_RULES: OpenAiRules = {
  maxOutput: null,
  forcedToolChoice: false,
  thinking: { on: 'none', offMode: 'omit' },
};

/* ─── Reasoning ─────────────────────────────────────────────── */

export interface ResolvedReasoning {
  reasoning?: Record<string, unknown>;
  /** Ask for `reasoning.encrypted_content` so reasoning items can be replayed statelessly. */
  includeEncryptedReasoning: boolean;
}

function lowestEffort(efforts: readonly string[] | undefined): string {
  if (!efforts || efforts.length === 0) return 'low';
  for (const level of EFFORT_LADDER) if (efforts.includes(level)) return level;
  return efforts.find((e) => e !== 'none') ?? efforts[0];
}

/**
 * Map the neutral thinking switch onto the model's rules.
 *
 *   on   `{effort: <registry default>, summary: 'auto'}`; the effort is left
 *        out when the registry states no default (the model then picks)
 *   off  none_effort  `{effort: 'none'}`
 *        low_effort   the lowest effort the model lists (a model without a
 *                     "none" level, or without "minimal", cannot be switched off)
 *        omit         no `reasoning` object at all
 *
 * `include: ['reasoning.encrypted_content']` goes with every request to a model
 * the registry says reasons, whether or not this request asks for it: the model
 * may still emit reasoning items, and a stateless replay needs their content.
 */
export function resolveReasoning(rules: OpenAiRules, wantThinking: boolean): ResolvedReasoning {
  const t = rules.thinking;
  if (t.on !== 'reasoning') return { includeEncryptedReasoning: false };
  if (wantThinking) {
    const reasoning: Record<string, unknown> = { summary: 'auto' };
    if (t.defaultEffort && (!t.efforts || t.efforts.includes(t.defaultEffort))) reasoning.effort = t.defaultEffort;
    return { reasoning, includeEncryptedReasoning: true };
  }
  switch (t.offMode) {
    case 'none_effort':
      return { reasoning: { effort: 'none' }, includeEncryptedReasoning: true };
    case 'low_effort':
      return { reasoning: { effort: lowestEffort(t.efforts) }, includeEncryptedReasoning: true };
    default:
      return { includeEncryptedReasoning: true };
  }
}

/* ─── Tools ─────────────────────────────────────────────────── */

// Converting a schema walks and inlines it, and the route reuses the same spec
// objects across calls, so the converted schema is cached per source schema.
const schemaCache = new WeakMap<object, Record<string, unknown>>();

function portableSchema(schema: Record<string, unknown>): Record<string, unknown> {
  if (typeof schema !== 'object' || schema === null) return toPortableSchema(schema);
  let converted = schemaCache.get(schema);
  if (!converted) {
    converted = toPortableSchema(schema);
    schemaCache.set(schema, converted);
  }
  return converted;
}

/**
 * Wire-named tool specs in the Responses API function-tool shape. `strict` is
 * off: MCP schemas are not strict-mode compatible (strict needs every property
 * required and `additionalProperties: false` throughout).
 */
export function openAiToolDefinitions(wireTools: ToolSpec[]): OpenAiTool[] {
  return wireTools.map((tool) => {
    const def: OpenAiTool = {
      type: 'function',
      name: tool.name,
      parameters: portableSchema(tool.inputSchema),
      strict: false,
    };
    if (tool.description && tool.description.trim()) def.description = tool.description;
    return def;
  });
}

/* ─── Replay ────────────────────────────────────────────────── */

export interface ReplayOptions {
  /**
   * Drop the `id` of every replayed item. Off by default: whether the API
   * accepts replayed ids under `store: false` is confirmed only by a live call,
   * and this flag is the one place to change if it does not.
   */
  stripIds?: boolean;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function messageHasContent(item: OpenAiItem): boolean {
  const content = item.content;
  if (typeof content === 'string') return content.trim() !== '';
  if (!Array.isArray(content)) return false;
  return content.some((part) => {
    if (!isObject(part)) return false;
    if (part.type === 'output_text' || part.type === 'input_text') {
      return typeof part.text === 'string' && part.text.trim() !== '';
    }
    if (part.type === 'refusal') return typeof part.refusal === 'string' && part.refusal.trim() !== '';
    return true;
  });
}

/**
 * The output items of an earlier assistant turn, as input items for the next
 * request. This is the whole of the stateless-replay policy, in one place:
 *
 *   - items go back verbatim and in order (ids, `status`, `phase` and
 *     `encrypted_content` untouched);
 *   - a `reasoning` item without `encrypted_content` is dropped: with nothing
 *     stored server side its id resolves to nothing and the request fails;
 *   - a `message` item with no text and no refusal is dropped;
 *   - `stripIds` (off by default) removes every `id`.
 */
export function replayItems(raw: unknown, opts: ReplayOptions = {}): OpenAiItem[] {
  if (!Array.isArray(raw)) return [];
  const out: OpenAiItem[] = [];
  for (const entry of raw) {
    if (!isObject(entry) || typeof entry.type !== 'string') continue;
    if (entry.type === 'reasoning') {
      const encrypted = entry.encrypted_content;
      if (typeof encrypted !== 'string' || encrypted === '') continue;
    }
    if (entry.type === 'message' && !messageHasContent(entry)) continue;
    const item: OpenAiItem = { ...entry };
    if (opts.stripIds) delete item.id;
    out.push(item);
  }
  return out;
}

/* ─── Messages ──────────────────────────────────────────────── */

function textMessage(role: 'user' | 'assistant', text: string): OpenAiItem[] {
  return text.trim() === '' ? [] : [{ type: 'message', role, content: text }];
}

function functionCallOutput(item: Extract<ToolResultItem, { kind: 'result' }>): OpenAiItem {
  return { type: 'function_call_output', call_id: item.callId, output: JSON.stringify(item.payload) };
}

function toItems(message: TurnMessage, replay: ReplayOptions): OpenAiItem[] {
  switch (message.role) {
    case 'user':
      return textMessage('user', message.text);
    case 'assistant':
      return textMessage('assistant', message.text);
    case 'assistant_turn':
      return replayItems(message.turn.raw, replay);
    case 'tool_results': {
      const out: OpenAiItem[] = [];
      for (const item of message.items) {
        if (item.kind === 'result') out.push(functionCallOutput(item));
      }
      // A directive follows every output, so it can never sit between a call
      // and its result.
      for (const item of message.items) {
        if (item.kind === 'directive') out.push(...textMessage('user', item.text));
      }
      return out;
    }
  }
}

/** Neutral messages -> Responses API input items. */
export function buildOpenAiInput(messages: TurnMessage[], replay: ReplayOptions = {}): OpenAiItem[] {
  const items: OpenAiItem[] = [];
  for (const message of messages) items.push(...toItems(message, replay));
  if (items.length === 0) items.push({ type: 'message', role: 'user', content: PLACEHOLDER_EMPTY_USER });
  return items;
}

/* ─── Request ───────────────────────────────────────────────── */

export function resolveMaxOutputTokens(rules: OpenAiRules, cap: number): number {
  return Math.min(rules.maxOutput ?? UNKNOWN_MODEL_MAX_TOKENS, cap);
}

/** SHA-256 hex of the session-derived key; the raw value is never sent. */
export function promptCacheKey(cacheKey: string): string {
  return createHash('sha256').update(cacheKey).digest('hex');
}

/**
 * Build the request body.
 *
 * `rules` is the registry's facts for the model (null when unknown);
 * `maxTokensCap` is `DEFAULT_RESERVED_OUTPUT_TOKENS`, passed in so this module
 * stays free of app imports.
 */
export function buildOpenAiRequest(
  req: ModelRequest,
  opts: { rules: OpenAiRules | null; maxTokensCap: number; replay?: ReplayOptions },
): BuiltOpenAiRequest {
  const rules = opts.rules ?? FALLBACK_RULES;
  const events: ProviderEvent[] = [];
  const codec = buildToolNameCodec(req.tools, 'openai');
  const tools = openAiToolDefinitions(codec.tools);
  const reasoning = resolveReasoning(rules, req.thinking);

  const body: Record<string, unknown> = { model: req.ref.model };
  if (req.system.trim()) body.instructions = req.system;
  body.input = buildOpenAiInput(req.messages, opts.replay);

  if (tools.length > 0) {
    body.tools = tools;
    body.parallel_tool_calls = true;
    if (req.toolChoice === 'none') {
      body.tool_choice = 'none';
    } else if (req.toolChoice === 'required') {
      if (rules.forcedToolChoice) {
        body.tool_choice = 'required';
      } else {
        body.tool_choice = 'auto';
        events.push({
          type: 'tool_choice_downgraded',
          message: 'Forced tool use was changed to auto because this model is not known to accept it.',
          data: { model: req.ref.model, requested: 'required', sent: 'auto' },
        });
      }
    } else {
      body.tool_choice = 'auto';
    }
  }

  body.max_output_tokens = resolveMaxOutputTokens(rules, opts.maxTokensCap);
  body.store = false;
  body.stream = true;
  if (reasoning.reasoning) body.reasoning = reasoning.reasoning;
  if (reasoning.includeEncryptedReasoning) body.include = ['reasoning.encrypted_content'];
  if (req.cacheKey) body.prompt_cache_key = promptCacheKey(req.cacheKey);

  return { body, events, codec };
}
