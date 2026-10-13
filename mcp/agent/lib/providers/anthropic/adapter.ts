/**
 * Anthropic Claude adapter over the Messages API (direct API key).
 *
 * `call` builds the request from the registry's rules for the model
 * (`payload.ts`), sends it as a stream with retries (`transport.ts`),
 * assembles the stream into one message (`stream.ts`) and returns a neutral
 * `AssistantTurn`: text, thinking summaries, tool calls decoded back to their
 * canonical names, usage, and the finish reason. `turn.raw` is the native
 * content-block list, replayed verbatim for the rest of the turn.
 *
 * The model's rules come from the registry's synchronous lookup; a model the
 * registry does not know is called with conservative defaults (no thinking
 * configuration, no forced tool choice, a 32K output cap).
 *
 * Credentials arrive in `ctx.creds` and are never read from the environment.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { DEFAULT_RESERVED_OUTPUT_TOKENS } from '../../model-context-caps.ts';
import { ProviderError, redactSecrets } from '../errors.ts';
import { fetchAnthropicModels } from '../registry/live.ts';
import { ANTHROPIC_CATALOG } from '../registry/catalog-anthropic.ts';
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
import {
  anthropicToolDefinitions,
  buildAnthropicRequest,
  type AnthropicRules,
} from './payload.ts';
import { mapAnthropicUsage, type AssembledMessage } from './stream.ts';
import { callAnthropicMessages, type AnthropicTransportDeps } from './transport.ts';

export interface AnthropicAdapterDeps extends AnthropicTransportDeps {
  /** Rules for a model id; defaults to the registry's synchronous lookup. */
  lookupRules?: (model: string) => AnthropicRules | null;
  /** Output cap applied to `max_tokens`; defaults to the budget walk's reserved output. */
  maxTokensCap?: number;
}

const ANTHROPIC_CAPABILITIES: AdapterCapabilities = { leakRecovery: false, emptyTurnRetry: false };

/* ─── Response ──────────────────────────────────────────────── */

export function mapStopReason(stopReason: string | null, hasToolCalls: boolean): FinishReason {
  switch (stopReason) {
    case 'end_turn':
    case 'stop_sequence':
      return 'stop';
    case 'tool_use':
      return hasToolCalls ? 'tool_use' : 'other';
    case 'max_tokens':
      return 'max_tokens';
    case 'refusal':
      return 'refusal';
    case 'model_context_window_exceeded':
      return 'context_exceeded';
    case 'pause_turn':
      return 'other';
    default:
      return hasToolCalls ? 'tool_use' : 'other';
  }
}

export function toAssistantTurn(
  message: AssembledMessage,
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
  for (const block of message.content) {
    if (block.type === 'text' && typeof block.text === 'string') {
      text.push(block.text);
    } else if (block.type === 'thinking' && typeof block.thinking === 'string' && block.thinking) {
      thinking.push(block.thinking);
    } else if (block.type === 'tool_use') {
      const wire = typeof block.name === 'string' ? block.name : '';
      const decoded = info.decodeName(wire);
      if (decoded === undefined) {
        info.onEvent?.({
          type: 'unknown_tool_name',
          message: 'The model called a tool name that was not in this request\'s catalog.',
          data: { name: wire },
        });
      }
      toolCalls.push({
        id: typeof block.id === 'string' ? block.id : '',
        name: decoded ?? wire,
        args: block.input && typeof block.input === 'object' ? (block.input as Record<string, unknown>) : {},
      });
    }
  }
  for (const cut of message.truncatedToolCalls) {
    info.onEvent?.({
      type: 'tool_call_truncated',
      message: 'A tool call was cut off by the output limit and was dropped.',
      data: { name: cut.name },
    });
  }
  const finish = mapStopReason(message.stopReason, toolCalls.length > 0);
  if (finish === 'refusal') {
    info.onEvent?.({
      type: 'refusal',
      message: 'The model declined to answer.',
      data: message.stopDetails === undefined ? {} : { stop_details: message.stopDetails },
    });
  }
  const turn: AssistantTurn = {
    provider: 'anthropic',
    model: info.model,
    text,
    thinking,
    toolCalls,
    finish,
    usage: mapAnthropicUsage(message.usage),
    leakedToolCallSuspected: false,
    raw: message.content,
  };
  if (message.stopReason) turn.finishDetail = message.stopReason;
  if (info.requestId) turn.requestId = info.requestId;
  return turn;
}

/* ─── Errors ────────────────────────────────────────────────── */

export function classifyAnthropicError(err: unknown): ProviderError {
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

export function createAnthropicAdapter(deps: AnthropicAdapterDeps = {}): ProviderAdapter {
  const lookupRules =
    deps.lookupRules ?? ((model: string) => lookupModelFacts(`anthropic/${model}`));
  const maxTokensCap = deps.maxTokensCap ?? DEFAULT_RESERVED_OUTPUT_TOKENS;

  return {
    id: 'anthropic',
    capabilities: ANTHROPIC_CAPABILITIES,

    estimateToolsPayload(tools: ToolSpec[]) {
      try {
        return anthropicToolDefinitions(buildToolNameCodec(tools, 'claude').tools);
      } catch {
        // A name collision is reported by the real call; the estimate just needs a size.
        return tools;
      }
    },

    async call(req: ModelRequest, ctx: CallContext): Promise<AssistantTurn> {
      const built = buildAnthropicRequest(req, {
        rules: lookupRules(req.ref.model),
        maxTokensCap,
      });
      for (const event of built.events) ctx.onEvent?.(event);
      const { message, requestId } = await callAnthropicMessages(
        built.body,
        built.betas,
        ctx.creds,
        deps,
        ctx.signal,
      );
      return toAssistantTurn(message, {
        model: req.ref.model,
        decodeName: built.codec.decode,
        requestId,
        onEvent: ctx.onEvent,
      });
    },

    async listModels(creds: ProviderCreds, signal: AbortSignal): Promise<LiveModel[]> {
      return await fetchAnthropicModels(creds, {
        fetch: deps.fetch,
        blockedHosts: deps.blockedHosts,
        resolveHost: deps.resolveHost,
        signal,
      });
    },

    async testConnection(creds: ProviderCreds) {
      try {
        const models = await fetchAnthropicModels(creds, {
          fetch: deps.fetch,
          blockedHosts: deps.blockedHosts,
          resolveHost: deps.resolveHost,
        });
        const ids = new Set(models.map((m) => m.id));
        const recommended = ANTHROPIC_CATALOG.filter((m) => ids.has(m.model)).map((m) => m.displayName);
        const detail =
          recommended.length > 0
            ? `, including ${recommended.join(', ')}`
            : '; none of the recommended Claude models are visible to this key';
        return {
          ok: true,
          status: 200,
          modelCount: models.length,
          message: `Connected. ${models.length} model${models.length === 1 ? '' : 's'} visible${detail}.`,
        };
      } catch (err) {
        const failure = classifyAnthropicError(err);
        return { ok: false, status: failure.status, message: failure.message };
      }
    },

    classifyError: classifyAnthropicError,
  };
}
