/**
 * Assemble a streamed Messages API response into one finished message.
 *
 * Events handled: `message_start`, `content_block_start`, `content_block_delta`
 * (`text_delta`, `input_json_delta`, `thinking_delta`, `signature_delta`,
 * `citations_delta`), `content_block_stop`, `message_delta`, `message_stop`,
 * `ping` (ignored) and `error` (thrown as a `ProviderError`).
 *
 * Every content block is built from its `content_block_start` object with the
 * deltas applied on top, so a `redacted_thinking` block, an unfamiliar block
 * type or an extra field survives verbatim. That list is what the next request
 * replays as the assistant turn, so thinking text and signatures are never
 * reshaped. Two deliberate exceptions, because the API rejects both on replay:
 * a text block that stayed blank is left out, and a `tool_use` whose streamed
 * JSON never became valid (the output was cut off) is left out and reported.
 *
 * Usage: `message_start.usage` seeds the totals and each `message_delta.usage`
 * is cumulative, so fields are merged with `max`, never summed.
 *
 * Nothing is handed to the caller until the message is complete, so a stream
 * that fails part way is safe to retry in full.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { readSse, type SseEvent } from '../sse.ts';
import type { NeutralUsage } from '../types.ts';
import { providerErrorFromApi, streamBrokenError } from './errors.ts';

type Json = Record<string, unknown>;

function isObject(v: unknown): v is Json {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export interface TruncatedToolCall {
  id: string;
  name: string;
}

export interface AssembledMessage {
  id?: string;
  model?: string;
  /** Native content blocks, in order, ready to replay as the assistant turn. */
  content: Json[];
  stopReason: string | null;
  stopDetails?: unknown;
  /** The merged raw usage object. */
  usage: Json;
  truncatedToolCalls: TruncatedToolCall[];
}

interface BlockState {
  block: Json;
  json: string;
  /** Set when the tool input never parsed. */
  truncated: boolean;
  finished: boolean;
}

/** Merge cumulative usage: numbers take the larger value, anything else overwrites. */
export function mergeUsage(target: Json, source: unknown): void {
  if (!isObject(source)) return;
  for (const [key, value] of Object.entries(source)) {
    if (value === null || value === undefined) continue;
    if (typeof value === 'number') {
      const prev = target[key];
      target[key] = typeof prev === 'number' ? Math.max(prev, value) : value;
    } else if (isObject(value)) {
      const prev = isObject(target[key]) ? (target[key] as Json) : {};
      mergeUsage(prev, value);
      target[key] = prev;
    } else {
      target[key] = value;
    }
  }
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0;
}

/**
 * Raw Messages API usage -> neutral usage. Input is the uncached tokens plus
 * cache reads plus cache writes; the 5-minute and 1-hour write split comes from
 * `cache_creation`. Output includes thinking tokens, which the API bills as
 * output and does not break out.
 */
export function mapAnthropicUsage(usage: Json | null | undefined): NeutralUsage | null {
  if (!usage || Object.keys(usage).length === 0) return null;
  const creation = isObject(usage.cache_creation) ? usage.cache_creation : {};
  const write5m = num(creation.ephemeral_5m_input_tokens);
  const write1h = num(creation.ephemeral_1h_input_tokens);
  // The flat total, else the sum of the tiers when only the breakdown came.
  const cacheWrite = num(usage.cache_creation_input_tokens) || write5m + write1h;
  const cacheRead = num(usage.cache_read_input_tokens);
  return {
    inputTotal: num(usage.input_tokens) + cacheWrite + cacheRead,
    cacheRead,
    cacheWrite,
    cacheWrite1h: Math.min(write1h, cacheWrite),
    output: num(usage.output_tokens),
    reasoning: 0,
  };
}

export interface StreamAssembler {
  push(event: SseEvent): void;
  /** True once `message_stop` arrived. */
  readonly done: boolean;
  /** The finished message; throws a retryable error when the stream ended early. */
  finish(): AssembledMessage;
}

export function createStreamAssembler(requestId?: string): StreamAssembler {
  let id: string | undefined;
  let model: string | undefined;
  let stopReason: string | null = null;
  let stopDetails: unknown;
  let done = false;
  const usage: Json = {};
  const blocks = new Map<number, BlockState>();

  function malformed(what: string): never {
    throw streamBrokenError(`The Anthropic stream was malformed (${what}).`);
  }

  function blockAt(index: unknown, what: string): BlockState {
    const state = typeof index === 'number' ? blocks.get(index) : undefined;
    if (!state) malformed(`${what} for an unknown block`);
    return state;
  }

  function finishBlock(state: BlockState): void {
    if (state.finished) return;
    state.finished = true;
    if (state.block.type !== 'tool_use') return;
    if (state.json.trim() === '') {
      state.block.input = {};
      return;
    }
    try {
      const parsed: unknown = JSON.parse(state.json);
      if (isObject(parsed)) state.block.input = parsed;
      else state.truncated = true;
    } catch {
      state.truncated = true;
    }
  }

  function handle(type: string, data: Json): void {
    switch (type) {
      case 'ping':
        return;
      case 'error':
        throw providerErrorFromApi({ body: data, requestId });
      case 'message_start': {
        const message = isObject(data.message) ? data.message : {};
        if (typeof message.id === 'string') id = message.id;
        if (typeof message.model === 'string') model = message.model;
        mergeUsage(usage, message.usage);
        return;
      }
      case 'content_block_start': {
        if (typeof data.index !== 'number' || !isObject(data.content_block)) malformed('block start');
        const block = structuredClone(data.content_block) as Json;
        if (block.type === 'text' && typeof block.text !== 'string') block.text = '';
        if (block.type === 'thinking' && typeof block.thinking !== 'string') block.thinking = '';
        if (block.type === 'tool_use' && !isObject(block.input)) block.input = {};
        // A tool_use start may carry a complete input already; deltas build on an empty buffer.
        blocks.set(data.index, { block, json: '', truncated: false, finished: false });
        return;
      }
      case 'content_block_delta': {
        const state = blockAt(data.index, 'a delta');
        const delta = isObject(data.delta) ? data.delta : {};
        const block = state.block;
        switch (delta.type) {
          case 'text_delta':
            block.text = `${typeof block.text === 'string' ? block.text : ''}${typeof delta.text === 'string' ? delta.text : ''}`;
            return;
          case 'input_json_delta':
            if (typeof delta.partial_json === 'string') state.json += delta.partial_json;
            return;
          case 'thinking_delta':
            block.thinking = `${typeof block.thinking === 'string' ? block.thinking : ''}${typeof delta.thinking === 'string' ? delta.thinking : ''}`;
            return;
          case 'signature_delta':
            block.signature = `${typeof block.signature === 'string' ? block.signature : ''}${typeof delta.signature === 'string' ? delta.signature : ''}`;
            return;
          case 'citations_delta': {
            const list = Array.isArray(block.citations) ? (block.citations as unknown[]) : [];
            if (delta.citation !== undefined) list.push(delta.citation);
            block.citations = list;
            return;
          }
          default:
            // A delta type this reader does not know changes nothing it replays.
            return;
        }
      }
      case 'content_block_stop':
        finishBlock(blockAt(data.index, 'a stop'));
        return;
      case 'message_delta': {
        const delta = isObject(data.delta) ? data.delta : {};
        if (typeof delta.stop_reason === 'string') stopReason = delta.stop_reason;
        if (delta.stop_details !== undefined && delta.stop_details !== null) stopDetails = delta.stop_details;
        mergeUsage(usage, data.usage);
        return;
      }
      case 'message_stop':
        done = true;
        return;
      default:
        // Future event types are skipped, as the streaming guide advises.
        return;
    }
  }

  return {
    push(event: SseEvent): void {
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        if (event.event === 'ping') return;
        throw streamBrokenError('The Anthropic stream carried data that was not JSON.');
      }
      if (!isObject(data)) return;
      const type = typeof data.type === 'string' ? data.type : (event.event ?? '');
      handle(type, data);
    },
    get done() {
      return done;
    },
    finish(): AssembledMessage {
      if (!done) throw streamBrokenError('The Anthropic stream ended before message_stop.');
      const content: Json[] = [];
      const truncatedToolCalls: TruncatedToolCall[] = [];
      for (const index of [...blocks.keys()].sort((a, b) => a - b)) {
        const state = blocks.get(index) as BlockState;
        finishBlock(state);
        const block = state.block;
        if (block.type === 'tool_use' && state.truncated) {
          truncatedToolCalls.push({
            id: typeof block.id === 'string' ? block.id : '',
            name: typeof block.name === 'string' ? block.name : '',
          });
          continue;
        }
        if (block.type === 'text' && (typeof block.text !== 'string' || block.text.trim() === '')) continue;
        content.push(block);
      }
      return { id, model, content, stopReason, stopDetails, usage, truncatedToolCalls };
    },
  };
}

/** Read a whole SSE body into one message. `onChunk` runs for every network chunk. */
export async function readAnthropicStream(
  body: ReadableStream<Uint8Array>,
  opts: { onChunk?: () => void; requestId?: string } = {},
): Promise<AssembledMessage> {
  const assembler = createStreamAssembler(opts.requestId);
  // Errors from the reader (an abort, a reset connection) propagate as they are;
  // the transport turns them into provider errors.
  for await (const event of readSse(body, { onChunk: opts.onChunk })) {
    assembler.push(event);
    if (assembler.done) break;
  }
  return assembler.finish();
}
