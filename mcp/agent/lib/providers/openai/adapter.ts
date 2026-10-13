/**
 * OpenAI adapter over the Responses API (direct API key).
 *
 * `call` builds the request from the registry's rules for the model
 * (`payload.ts`), sends it as a stream with retries (`transport.ts`),
 * assembles the stream into one response (`stream.ts`) and returns a neutral
 * `AssistantTurn`: text, reasoning summaries, tool calls decoded back to their
 * canonical names, usage, and the finish reason. `turn.raw` is the native
 * output-item list, replayed through `replayItems` for the rest of the turn.
 *
 * The model's rules come from the registry's synchronous lookup; a model the
 * registry does not know is called with conservative defaults (no reasoning
 * configuration, no forced tool choice, a 32K output cap).
 *
 * Credentials arrive in `ctx.creds` and are never read from the environment.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { DEFAULT_RESERVED_OUTPUT_TOKENS } from '../../model-context-caps.ts';
import { ProviderError, redactSecrets } from '../errors.ts';
import { OPENAI_CATALOG } from '../registry/catalog-openai.ts';
import { fetchOpenAiModels } from '../registry/live.ts';
import { lookupModelFacts } from '../registry/lookup.ts';
import { buildToolNameCodec } from '../tool-names.ts';
import type {
  AdapterCapabilities,
  AssistantTurn,
  CallContext,
  FinishReason,
  LiveModel,
  ModelRequest,
  ProviderAdapter,
  ProviderCreds,
  ProviderEvent,
  ToolCall,
  ToolSpec,
} from '../types.ts';
import { buildOpenAiRequest, openAiToolDefinitions, type OpenAiRules, type ReplayOptions } from './payload.ts';
import { mapOpenAiUsage, parseCallArguments, type AssembledResponse } from './stream.ts';
import { callOpenAiResponses, type OpenAiTransportDeps } from './transport.ts';

export interface OpenAiAdapterDeps extends OpenAiTransportDeps {
  /** Rules for a model id; defaults to the registry's synchronous lookup. */
  lookupRules?: (model: string) => OpenAiRules | null;
  /** Output cap applied to `max_output_tokens`; defaults to the budget walk's reserved output. */
  maxTokensCap?: number;
  /** Replay policy for earlier output items; see `replayItems`. */
  replay?: ReplayOptions;
}

const OPENAI_CAPABILITIES: AdapterCapabilities = { leakRecovery: false, emptyTurnRetry: false };

type Json = Record<string, unknown>;

function isObject(v: unknown): v is Json {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/* ─── Response ──────────────────────────────────────────────── */

/**
 * `completed` is a stop, or a tool turn when calls came back; `incomplete`
 * reports why it stopped early. A refusal is decided by the caller from the
 * output items, not here.
 */
export function mapResponseStatus(status: string, incompleteReason: string | undefined, hasToolCalls: boolean): FinishReason {
  switch (status) {
    case 'completed':
      return hasToolCalls ? 'tool_use' : 'stop';
    case 'incomplete':
      if (incompleteReason === 'max_output_tokens') return 'max_tokens';
      if (incompleteReason === 'content_filter') return 'safety';
      return 'other';
    default:
      return hasToolCalls ? 'tool_use' : 'other';
  }
}

export function toAssistantTurn(
  response: AssembledResponse,
  info: {
    model: string;
    decodeName: (wire: string) => string | undefined;
    requestId?: string;
    onEvent?: (event: ProviderEvent) => void;
  },
): AssistantTurn {
  const text: string[] = [];
  const thinking: string[] = [];
  const toolCalls: ToolCall[] = [];
  const refusals: string[] = [];

  for (const item of response.items) {
    if (item.type === 'message' && Array.isArray(item.content)) {
      for (const part of item.content) {
        if (!isObject(part)) continue;
        if (part.type === 'output_text' && typeof part.text === 'string') text.push(part.text);
        else if (part.type === 'refusal' && typeof part.refusal === 'string' && part.refusal) refusals.push(part.refusal);
      }
    } else if (item.type === 'reasoning' && Array.isArray(item.summary)) {
      for (const part of item.summary) {
        if (isObject(part) && typeof part.text === 'string' && part.text) thinking.push(part.text);
      }
    } else if (item.type === 'function_call') {
      const wire = typeof item.name === 'string' ? item.name : '';
      const decoded = info.decodeName(wire);
      if (decoded === undefined) {
        info.onEvent?.({
          type: 'unknown_tool_name',
          message: 'The model called a tool name that was not in this request\'s catalog.',
          data: { name: wire },
        });
      }
      const id = typeof item.call_id === 'string' && item.call_id ? item.call_id : typeof item.id === 'string' ? item.id : '';
      toolCalls.push({ id, name: decoded ?? wire, args: parseCallArguments(item.arguments) ?? {} });
    }
  }
  for (const cut of response.truncatedToolCalls) {
    info.onEvent?.({
      type: 'tool_call_truncated',
      message: 'A tool call was cut off by the output limit and was dropped.',
      data: { name: cut.name },
    });
  }

  let finish = mapResponseStatus(response.status, response.incompleteReason, toolCalls.length > 0);
  if (refusals.length > 0) {
    // The refusal text is the model's own explanation, so it is shown as the
    // reply; the route's generic wording applies only when there is no text.
    text.push(...refusals);
    finish = 'refusal';
    info.onEvent?.({
      type: 'refusal',
      message: 'The model declined to answer.',
      data: { chars: refusals.join('').length },
    });
  }

  const turn: AssistantTurn = {
    provider: 'openai',
    model: info.model,
    text,
    thinking,
    toolCalls,
    finish,
    usage: mapOpenAiUsage(response.usage),
    leakedToolCallSuspected: false,
    raw: response.items,
  };
  turn.finishDetail = response.incompleteReason ? `${response.status}:${response.incompleteReason}` : response.status;
  if (info.requestId) turn.requestId = info.requestId;
  return turn;
}

/* ─── Errors ────────────────────────────────────────────────── */

export function classifyOpenAiError(err: unknown): ProviderError {
  if (err instanceof ProviderError) return err;
  const message = err instanceof Error ? err.message : String(err);
  const network = /fetch failed|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|network|socket/i.test(message);
  return new ProviderError({
    kind: network ? 'network' : 'unknown',
    retryable: network,
    message: redactSecrets(message),
    cause: err,
  });
}

/* ─── Adapter ───────────────────────────────────────────────── */

export function createOpenAiAdapter(deps: OpenAiAdapterDeps = {}): ProviderAdapter {
  const lookupRules = deps.lookupRules ?? ((model: string) => lookupModelFacts(`openai/${model}`));
  const maxTokensCap = deps.maxTokensCap ?? DEFAULT_RESERVED_OUTPUT_TOKENS;

  return {
    id: 'openai',
    capabilities: OPENAI_CAPABILITIES,

    estimateToolsPayload(tools: ToolSpec[]) {
      try {
        return openAiToolDefinitions(buildToolNameCodec(tools, 'openai').tools);
      } catch {
        // A name collision is reported by the real call; the estimate just needs a size.
        return tools;
      }
    },

    async call(req: ModelRequest, ctx: CallContext): Promise<AssistantTurn> {
      const built = buildOpenAiRequest(req, {
        rules: lookupRules(req.ref.model),
        maxTokensCap,
        replay: deps.replay,
      });
      for (const event of built.events) ctx.onEvent?.(event);
      const { response, requestId } = await callOpenAiResponses(built.body, ctx.creds, deps, ctx.signal);
      return toAssistantTurn(response, {
        model: req.ref.model,
        decodeName: built.codec.decode,
        requestId,
        onEvent: ctx.onEvent,
      });
    },

    async listModels(creds: ProviderCreds, signal: AbortSignal): Promise<LiveModel[]> {
      return await fetchOpenAiModels(creds, {
        fetch: deps.fetch,
        blockedHosts: deps.blockedHosts,
        resolveHost: deps.resolveHost,
        signal,
      });
    },

    async testConnection(creds: ProviderCreds) {
      try {
        const models = await fetchOpenAiModels(creds, {
          fetch: deps.fetch,
          blockedHosts: deps.blockedHosts,
          resolveHost: deps.resolveHost,
        });
        const ids = new Set(models.map((m) => m.id));
        const recommended = OPENAI_CATALOG.filter((m) => ids.has(m.model)).map((m) => m.displayName);
        const detail =
          recommended.length > 0
            ? `, including ${recommended.join(', ')}`
            : '; none of the recommended OpenAI models are visible to this key';
        return {
          ok: true,
          status: 200,
          modelCount: models.length,
          message: `Connected. ${models.length} model${models.length === 1 ? '' : 's'} visible${detail}.`,
        };
      } catch (err) {
        const failure = classifyOpenAiError(err);
        return { ok: false, status: failure.status, message: failure.message };
      }
    },

    classifyError: classifyOpenAiError,
  };
}
