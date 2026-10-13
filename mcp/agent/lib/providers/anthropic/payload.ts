/**
 * Anthropic Messages API request builder: neutral `ModelRequest` in, the JSON
 * body for `POST /v1/messages` out. Pure; nothing here touches the network.
 *
 * What the mapping guarantees (each is a 400 from the API otherwise):
 *   - `system` is a block list whose block carries `cache_control`; it is
 *     omitted when empty (an empty text block is rejected);
 *   - roles alternate: adjacent same-role messages are merged, the first
 *     message is the user's (a placeholder is prepended when it is not), and
 *     the last is the user's (a prefilled assistant turn is rejected on the
 *     current models);
 *   - a tool-result message carries its `tool_result` blocks first, then any
 *     directive as a text block;
 *   - blank text blocks are dropped, and a message left empty is dropped;
 *   - an in-loop assistant turn is replayed through its native content blocks
 *     (`turn.raw`), thinking blocks and signatures untouched;
 *   - `temperature`, `top_p` and `top_k` are never sent (non-default values
 *     are rejected on the current models);
 *   - tools use the wire names of the tool-name codec; with no tools, neither
 *     `tools` nor `tool_choice` is sent.
 *
 * The model's thinking rules (from the registry) decide what `thinking`,
 * `output_config` and `tool_choice` look like; see `resolveThinking`.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import type { ModelFacts } from '../registry/lookup.ts';
import { toPortableSchema } from '../schema.ts';
import { buildToolNameCodec, type ToolNameCodec } from '../tool-names.ts';
import type { ModelRequest, ProviderEvent, ToolResultItem, ToolSpec, TurnMessage } from '../types.ts';

/** The registry facts this builder reads. A model the registry does not know passes null. */
export type AnthropicRules = Pick<ModelFacts, 'maxOutput' | 'forcedToolChoice' | 'thinking'>;

export type AnthropicBlock = Record<string, unknown>;
export interface AnthropicMessage {
  role: 'user' | 'assistant';
  content: AnthropicBlock[];
}

export interface AnthropicTool {
  name: string;
  description?: string;
  input_schema: Record<string, unknown>;
}

export interface BuiltAnthropicRequest {
  body: Record<string, unknown>;
  /** Names for the single comma-joined `anthropic-beta` header; empty means no header. */
  betas: string[];
  /** Observations the adapter reports through `onEvent`. */
  events: ProviderEvent[];
  codec: ToolNameCodec;
}

/** Output cap for a model whose maximum the registry does not state. */
export const UNKNOWN_MODEL_MAX_TOKENS = 32_000;

/** Smallest `budget_tokens` the API accepts; used by the budgeted-thinking mode. */
const MIN_THINKING_BUDGET = 1024;
const THINKING_BUDGET = 16_000;

const EFFORT_LADDER = ['low', 'medium', 'high', 'xhigh', 'max'] as const;

const FALLBACK_RULES: AnthropicRules = {
  maxOutput: null,
  forcedToolChoice: false,
  thinking: { on: 'none', offMode: 'omit' },
};

/** Purposes whose prompt is worth caching: they sit inside a tool loop and are re-read. */
const CACHED_PURPOSES: ReadonlySet<ModelRequest['purpose']> = new Set(['chat', 'subagent', 'budget_summary']);

/* ─── Thinking ──────────────────────────────────────────────── */

export interface ResolvedThinking {
  thinking?: Record<string, unknown>;
  outputConfig?: Record<string, unknown>;
  /** The model will reason before or between calls. Forced tool choice is rejected then. */
  engaged: boolean;
}

function lowestEffort(efforts: readonly string[] | undefined): string {
  if (!efforts || efforts.length === 0) return 'low';
  for (const level of EFFORT_LADDER) if (efforts.includes(level)) return level;
  return efforts[0];
}

/**
 * Map the neutral thinking switch onto the model's rules.
 *
 *   on  adaptive        {type: adaptive, display: summarized}; effort stays the model default
 *       enabled_budget  {type: enabled, budget_tokens} below max_tokens (older models)
 *   off disabled        {type: disabled}
 *       between_tools   {type: between_tools}             (Sonnet 5.5 rejects disabled)
 *       low_effort      thinking cannot be switched off:    (Opus 5.5, Fable 5.1)
 *                       output_config.effort = lowest, thinking left to the default
 *       omit            nothing sent
 *
 * `display` is never sent with `disabled` or `between_tools`. Effort is sent
 * only for the low-effort case, so it does not drift within a turn.
 */
export function resolveThinking(rules: AnthropicRules, wantThinking: boolean, maxTokens: number): ResolvedThinking {
  const t = rules.thinking;
  if (wantThinking) {
    if (t.on === 'adaptive') return { thinking: { type: 'adaptive', display: 'summarized' }, engaged: true };
    if (t.on === 'enabled_budget') {
      const budget = Math.min(THINKING_BUDGET, maxTokens - 1);
      if (budget >= MIN_THINKING_BUDGET) {
        return { thinking: { type: 'enabled', budget_tokens: budget }, engaged: true };
      }
    }
    return { engaged: false };
  }
  if (t.on === 'none') return { engaged: false };
  switch (t.offMode) {
    case 'disabled':
      return { thinking: { type: 'disabled' }, engaged: false };
    case 'between_tools':
      return { thinking: { type: 'between_tools' }, engaged: true };
    case 'low_effort':
      return { outputConfig: { effort: lowestEffort(t.efforts) }, engaged: true };
    default:
      return { engaged: false };
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

/** Wire-named tool specs in the Messages API tool shape. */
export function anthropicToolDefinitions(wireTools: ToolSpec[]): AnthropicTool[] {
  return wireTools.map((tool) => {
    const def: AnthropicTool = { name: tool.name, input_schema: portableSchema(tool.inputSchema) };
    if (tool.description && tool.description.trim()) def.description = tool.description;
    return def;
  });
}

/* ─── Messages ──────────────────────────────────────────────── */

function isBlankText(block: AnthropicBlock): boolean {
  return block.type === 'text' && (typeof block.text !== 'string' || block.text.trim() === '');
}

function textBlock(text: string): AnthropicBlock[] {
  return text.trim() === '' ? [] : [{ type: 'text', text }];
}

function toolResultBlock(item: Extract<ToolResultItem, { kind: 'result' }>): AnthropicBlock {
  const block: AnthropicBlock = {
    type: 'tool_result',
    tool_use_id: item.callId,
    content: JSON.stringify(item.payload),
  };
  if (item.payload.error !== undefined) block.is_error = true;
  return block;
}

function isThinkingBlock(block: AnthropicBlock): boolean {
  return block.type === 'thinking' || block.type === 'redacted_thinking';
}

/**
 * Prior assistant turns' thinking blocks are bound to the request that made
 * them. When a request turns thinking off for good (a disabled mode, not the
 * low-effort or between-tools modes, where the model keeps thinking and its
 * blocks must come back unchanged), replaying them risks a 400, so they are
 * dropped. Live verification pending.
 */
export function stripThinkingBlocks(blocks: AnthropicBlock[]): AnthropicBlock[] {
  return blocks.filter((block) => !isThinkingBlock(block));
}

function toAnthropicMessage(message: TurnMessage, stripThinking: boolean): AnthropicMessage | null {
  switch (message.role) {
    case 'user': {
      const content = textBlock(message.text);
      return content.length ? { role: 'user', content } : null;
    }
    case 'assistant': {
      const content = textBlock(message.text);
      return content.length ? { role: 'assistant', content } : null;
    }
    case 'assistant_turn': {
      const raw = Array.isArray(message.turn.raw) ? (message.turn.raw as AnthropicBlock[]) : [];
      let content = raw.filter((block) => !isBlankText(block));
      if (stripThinking) content = stripThinkingBlocks(content);
      return content.length ? { role: 'assistant', content } : null;
    }
    case 'tool_results': {
      const content: AnthropicBlock[] = [];
      for (const item of message.items) {
        if (item.kind === 'result') content.push(toolResultBlock(item));
      }
      for (const item of message.items) {
        if (item.kind === 'directive') content.push(...textBlock(item.text));
      }
      return content.length ? { role: 'user', content } : null;
    }
  }
}

/** Put `tool_result` blocks first, keeping the relative order within each group. */
function toolResultsFirst(content: AnthropicBlock[]): AnthropicBlock[] {
  const results = content.filter((b) => b.type === 'tool_result');
  if (results.length === 0 || results.length === content.length) return content;
  return [...results, ...content.filter((b) => b.type !== 'tool_result')];
}

export const PLACEHOLDER_FIRST_USER = '(conversation history follows)';
export const PLACEHOLDER_LAST_USER = 'Continue.';
export const PLACEHOLDER_EMPTY_USER = '(no content)';

/** Neutral messages -> alternating Messages API messages. */
export function buildAnthropicMessages(messages: TurnMessage[], opts: { stripThinking: boolean }): AnthropicMessage[] {
  const merged: AnthropicMessage[] = [];
  for (const message of messages) {
    const converted = toAnthropicMessage(message, opts.stripThinking);
    if (!converted) continue;
    const last = merged[merged.length - 1];
    if (last && last.role === converted.role) last.content = [...last.content, ...converted.content];
    else merged.push({ role: converted.role, content: [...converted.content] });
  }
  for (const message of merged) {
    if (message.role === 'user') message.content = toolResultsFirst(message.content);
  }
  if (merged.length === 0) {
    return [{ role: 'user', content: [{ type: 'text', text: PLACEHOLDER_EMPTY_USER }] }];
  }
  if (merged[0].role === 'assistant') {
    merged.unshift({ role: 'user', content: [{ type: 'text', text: PLACEHOLDER_FIRST_USER }] });
  }
  if (merged[merged.length - 1].role === 'assistant') {
    merged.push({ role: 'user', content: [{ type: 'text', text: PLACEHOLDER_LAST_USER }] });
  }
  return merged;
}

/* ─── Request ───────────────────────────────────────────────── */

export function resolveMaxTokens(rules: AnthropicRules, cap: number): number {
  return Math.min(rules.maxOutput ?? UNKNOWN_MODEL_MAX_TOKENS, cap);
}

/**
 * Build the request body.
 *
 * `rules` is the registry's facts for the model (null when unknown);
 * `maxTokensCap` is `DEFAULT_RESERVED_OUTPUT_TOKENS`, passed in so this module
 * stays free of app imports.
 */
export function buildAnthropicRequest(
  req: ModelRequest,
  opts: { rules: AnthropicRules | null; maxTokensCap: number },
): BuiltAnthropicRequest {
  const rules = opts.rules ?? FALLBACK_RULES;
  const events: ProviderEvent[] = [];
  const maxTokens = resolveMaxTokens(rules, opts.maxTokensCap);
  const thinking = resolveThinking(rules, req.thinking, maxTokens);
  const codec = buildToolNameCodec(req.tools, 'claude');
  const tools = anthropicToolDefinitions(codec.tools);
  const cached = CACHED_PURPOSES.has(req.purpose);

  const body: Record<string, unknown> = {
    model: req.ref.model,
    max_tokens: maxTokens,
    stream: true,
  };

  if (req.system.trim()) {
    const block: AnthropicBlock = { type: 'text', text: req.system };
    if (cached) block.cache_control = { type: 'ephemeral' };
    body.system = [block];
  }

  // Prior thinking blocks are replayed unchanged whenever the model still
  // thinks (adaptive, between tools, or at the lowest effort) and dropped only
  // when this request switches thinking off for good.
  body.messages = buildAnthropicMessages(req.messages, { stripThinking: !thinking.engaged });

  if (tools.length > 0) {
    body.tools = tools;
    if (req.toolChoice === 'none') {
      body.tool_choice = { type: 'none' };
    } else if (req.toolChoice === 'required') {
      if (rules.forcedToolChoice && !thinking.engaged) {
        body.tool_choice = { type: 'any' };
      } else {
        events.push({
          type: 'tool_choice_downgraded',
          message: rules.forcedToolChoice
            ? 'Forced tool use was changed to auto because thinking is active on this model.'
            : 'Forced tool use was changed to auto because this model rejects it.',
          data: { model: req.ref.model, requested: 'required', sent: 'auto', thinkingActive: thinking.engaged },
        });
      }
    }
  }

  if (thinking.thinking) body.thinking = thinking.thinking;
  if (thinking.outputConfig) body.output_config = thinking.outputConfig;
  // Automatic caching: the breakpoint follows the conversation as the tool loop grows it.
  if (cached) body.cache_control = { type: 'ephemeral' };

  return { body, betas: [], events, codec };
}
