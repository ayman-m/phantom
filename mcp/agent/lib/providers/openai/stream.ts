/**
 * Assemble a streamed Responses API answer into one finished response.
 *
 * The stream is a series of `data:` events, each a JSON object whose `type`
 * names it. Handled here:
 *
 *   response.output_item.added / .done        an output item begins / is final
 *   response.output_text.delta / .done        message text
 *   response.refusal.delta / .done            refusal text
 *   response.function_call_arguments.delta / .done
 *   response.reasoning_summary_text.delta     reasoning summary text
 *   response.completed / .incomplete / .failed   terminal: carry the final
 *                                             `response` object, usage included
 *   error                                     thrown as a `ProviderError`
 *
 * Every other event (`response.created`, `.in_progress`, content-part and
 * annotation events, future types) is skipped, as the streaming guide advises.
 *
 * The output items are taken whole from the API, so `encrypted_content`, an
 * assistant `phase` and any field this reader does not know survive into the
 * replay verbatim. Sources, in order of trust:
 *   1. the terminal event's `response.output` array, when non-empty;
 *   2. else the items from `response.output_item.done`;
 *   3. else, as a last resort, items rebuilt from the deltas.
 * Correctness does not depend on the per-event bookkeeping fields (`item_id`,
 * `output_index`), whose exact names are still to be confirmed against live
 * traffic: a delta that cannot be placed is ignored, because the sources above
 * carry the same content.
 *
 * Deliberate exception to "verbatim": a `function_call` whose arguments never
 * became valid JSON (the output was cut off) is left out and reported. It could
 * not be answered, and a call with no output is a 400 on the next request.
 *
 * Nothing is handed to the caller until a terminal event arrives, so a stream
 * that fails part way is safe to retry in full.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { readSse, type SseEvent } from '../sse.ts';
import { streamBrokenError } from '../streaming-call.ts';
import type { NeutralUsage } from '../types.ts';
import { providerErrorFromApi } from './errors.ts';

type Json = Record<string, unknown>;

function isObject(v: unknown): v is Json {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0;
}

export interface TruncatedToolCall {
  id: string;
  name: string;
}

export interface AssembledResponse {
  id?: string;
  model?: string;
  /** `completed` or `incomplete` (a `failed` response is thrown, not returned). */
  status: string;
  /** `incomplete_details.reason`, e.g. `max_output_tokens`. */
  incompleteReason?: string;
  /** Native output items, in order, ready to replay as the assistant turn. */
  items: Json[];
  /** The raw usage object. */
  usage: Json;
  truncatedToolCalls: TruncatedToolCall[];
}

/**
 * The arguments of a `function_call` item as an object, or null when they are
 * not a complete JSON object. An absent or blank string is an empty object (a
 * tool with no parameters).
 */
export function parseCallArguments(args: unknown): Json | null {
  if (isObject(args)) return args;
  if (args === undefined || args === null) return {};
  if (typeof args !== 'string') return null;
  if (args.trim() === '') return {};
  try {
    const parsed: unknown = JSON.parse(args);
    return isObject(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Raw Responses API usage -> neutral usage. `input_tokens` already contains
 * the cached tokens (`input_tokens_details.cached_tokens`) and the cache-write
 * tokens (`input_tokens_details.cache_write_tokens`); `output_tokens` already
 * contains the reasoning tokens (`output_tokens_details.reasoning_tokens`),
 * which are billed as output.
 */
export function mapOpenAiUsage(usage: Json | null | undefined): NeutralUsage | null {
  if (!usage || Object.keys(usage).length === 0) return null;
  const inDetails = isObject(usage.input_tokens_details) ? usage.input_tokens_details : {};
  const outDetails = isObject(usage.output_tokens_details) ? usage.output_tokens_details : {};
  return {
    inputTotal: num(usage.input_tokens),
    cacheRead: num(inDetails.cached_tokens),
    cacheWrite: num(inDetails.cache_write_tokens),
    // One write tier (30 minutes) exists, priced as the single write rate.
    cacheWrite1h: 0,
    output: num(usage.output_tokens),
    reasoning: num(outDetails.reasoning_tokens),
  };
}

const TERMINAL_EVENTS = new Set(['response.completed', 'response.incomplete', 'response.failed']);

interface Slot {
  item: Json;
  done: boolean;
  /** Streamed function-call arguments. */
  args: string;
  text: Map<number, string>;
  refusal: Map<number, string>;
  summary: Map<number, string>;
}

function appendAt(map: Map<number, string>, index: unknown, piece: unknown): void {
  if (typeof piece !== 'string') return;
  const at = typeof index === 'number' ? index : 0;
  map.set(at, `${map.get(at) ?? ''}${piece}`);
}

function setAt(map: Map<number, string>, index: unknown, value: unknown): void {
  if (typeof value !== 'string') return;
  map.set(typeof index === 'number' ? index : 0, value);
}

function sortedValues(map: Map<number, string>): string[] {
  return [...map.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
}

/** Last resort: an item reconstructed from its deltas, for a stream that never sent `.done`. */
function rebuildItem(slot: Slot): Json {
  const item = structuredClone(slot.item);
  switch (item.type) {
    case 'function_call':
      if (slot.args) item.arguments = slot.args;
      break;
    case 'message': {
      const content: Json[] = [];
      for (const text of sortedValues(slot.text)) content.push({ type: 'output_text', text, annotations: [] });
      for (const refusal of sortedValues(slot.refusal)) content.push({ type: 'refusal', refusal });
      if (content.length > 0) item.content = content;
      break;
    }
    case 'reasoning': {
      const summary = sortedValues(slot.summary);
      if (summary.length > 0) item.summary = summary.map((text) => ({ type: 'summary_text', text }));
      break;
    }
    default:
      break;
  }
  return item;
}

export interface StreamAssembler {
  push(event: SseEvent): void;
  /** True once a terminal event arrived. */
  readonly done: boolean;
  /** The finished response; throws a retryable error when the stream ended early. */
  finish(): AssembledResponse;
}

export function createStreamAssembler(requestId?: string): StreamAssembler {
  const slots: Slot[] = [];
  const byIndex = new Map<number, Slot>();
  const byId = new Map<string, Slot>();
  let terminal: Json | null = null;
  let terminalType = '';

  function slotFor(data: Json): Slot | undefined {
    if (typeof data.output_index === 'number') {
      const hit = byIndex.get(data.output_index);
      if (hit) return hit;
    }
    if (typeof data.item_id === 'string') return byId.get(data.item_id);
    return undefined;
  }

  function register(data: Json, item: Json): Slot {
    const slot: Slot = { item: structuredClone(item), done: false, args: '', text: new Map(), refusal: new Map(), summary: new Map() };
    slots.push(slot);
    if (typeof data.output_index === 'number') byIndex.set(data.output_index, slot);
    if (typeof item.id === 'string') byId.set(item.id, slot);
    return slot;
  }

  function handle(type: string, data: Json): void {
    switch (type) {
      case 'error':
        throw providerErrorFromApi({ body: data, requestId });
      case 'response.output_item.added': {
        if (isObject(data.item)) register(data, data.item);
        return;
      }
      case 'response.output_item.done': {
        if (!isObject(data.item)) return;
        const slot = slotFor(data) ?? register(data, data.item);
        slot.item = structuredClone(data.item);
        slot.done = true;
        return;
      }
      case 'response.output_text.delta':
        appendAt(slotFor(data)?.text ?? new Map(), data.content_index, data.delta);
        return;
      case 'response.output_text.done': {
        const slot = slotFor(data);
        if (slot) setAt(slot.text, data.content_index, data.text);
        return;
      }
      case 'response.refusal.delta':
        appendAt(slotFor(data)?.refusal ?? new Map(), data.content_index, data.delta);
        return;
      case 'response.refusal.done': {
        const slot = slotFor(data);
        if (slot) setAt(slot.refusal, data.content_index, data.refusal);
        return;
      }
      case 'response.function_call_arguments.delta': {
        const slot = slotFor(data);
        if (slot && typeof data.delta === 'string') slot.args += data.delta;
        return;
      }
      case 'response.function_call_arguments.done': {
        const slot = slotFor(data);
        if (slot && typeof data.arguments === 'string') slot.args = data.arguments;
        return;
      }
      case 'response.reasoning_summary_text.delta':
        appendAt(slotFor(data)?.summary ?? new Map(), data.summary_index, data.delta);
        return;
      default:
        if (TERMINAL_EVENTS.has(type)) {
          const response = isObject(data.response) ? data.response : {};
          if (type === 'response.failed') {
            const error = isObject(response.error) ? response.error : {};
            throw providerErrorFromApi({
              body: { error: { ...error, message: typeof error.message === 'string' && error.message ? error.message : 'The response failed.' } },
              requestId,
            });
          }
          terminal = response;
          terminalType = type;
        }
        // Everything else (created, in_progress, content parts, annotations,
        // future event types) changes nothing this reader replays.
        return;
    }
  }

  return {
    push(event: SseEvent): void {
      if (event.data.trim() === '[DONE]') return;
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        throw streamBrokenError('The OpenAI stream carried data that was not JSON.');
      }
      if (!isObject(data)) return;
      const type = typeof data.type === 'string' ? data.type : (event.event ?? '');
      handle(type, data);
    },
    get done() {
      return terminal !== null;
    },
    finish(): AssembledResponse {
      if (terminal === null) throw streamBrokenError('The OpenAI stream ended before response.completed.');
      const response: Json = terminal;
      const output = Array.isArray(response.output) ? response.output.filter(isObject) : [];
      const source: Json[] =
        output.length > 0
          ? output.map((item) => structuredClone(item))
          : slots.map((slot) => (slot.done ? structuredClone(slot.item) : rebuildItem(slot)));

      const items: Json[] = [];
      const truncatedToolCalls: TruncatedToolCall[] = [];
      for (const item of source) {
        if (item.type === 'function_call' && parseCallArguments(item.arguments) === null) {
          truncatedToolCalls.push({
            id: typeof item.call_id === 'string' ? item.call_id : typeof item.id === 'string' ? item.id : '',
            name: typeof item.name === 'string' ? item.name : '',
          });
          continue;
        }
        items.push(item);
      }

      const details = isObject(response.incomplete_details) ? response.incomplete_details : {};
      const out: AssembledResponse = {
        status: typeof response.status === 'string' ? response.status : terminalType === 'response.incomplete' ? 'incomplete' : 'completed',
        items,
        usage: isObject(response.usage) ? structuredClone(response.usage) : {},
        truncatedToolCalls,
      };
      if (typeof response.id === 'string') out.id = response.id;
      if (typeof response.model === 'string') out.model = response.model;
      if (typeof details.reason === 'string') out.incompleteReason = details.reason;
      return out;
    },
  };
}

/** Read a whole SSE body into one response. `onChunk` runs for every network chunk. */
export async function readOpenAiStream(
  body: ReadableStream<Uint8Array>,
  opts: { onChunk?: () => void; requestId?: string } = {},
): Promise<AssembledResponse> {
  const assembler = createStreamAssembler(opts.requestId);
  // Errors from the reader (an abort, a reset connection) propagate as they are;
  // the transport turns them into provider errors.
  for await (const event of readSse(body, { onChunk: opts.onChunk })) {
    assembler.push(event);
    if (assembler.done) break;
  }
  return assembler.finish();
}
