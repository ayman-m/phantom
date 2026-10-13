/**
 * Gemini adapter: neutral `ModelRequest` in, neutral `AssistantTurn` out.
 *
 * The request side builds exactly the JSON the chat route has always sent
 * (see scripts/test-gemini-payload-parity.mjs): one Gemini `content` per
 * neutral message with no merging, `tools: []` when the neutral tool choice
 * is 'none', thinking config only when `thinking` is true, and the forced
 * function-calling config only for 'required'. The response side reads the
 * first candidate the way the route's loop does.
 *
 * Call ids are synthesized as `gem_<step>_<i>` because Gemini function calls
 * carry none; results are matched by position when replayed, as before.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { abortedError, ProviderError, redactSecrets } from '../errors.ts';
import { toGeminiSchema } from '../schema.ts';
import { buildToolNameCodec } from '../tool-names.ts';
import type {
  AdapterCapabilities,
  AssistantTurn,
  CallContext,
  FinishReason,
  LiveModel,
  ModelRequest,
  NeutralUsage,
  ProviderAdapter,
  ProviderCreds,
  ToolResultItem,
  ToolSpec,
  TurnMessage,
} from '../types.ts';
import {
  buildGeminiPayload,
  type GeminiCallPayload,
  type GeminiContent,
  type GeminiPart,
} from './payload.ts';
import {
  callGeminiGenerateContent,
  GEMINI_NO_PROVIDER_MESSAGES,
  type GeminiTransportDeps,
} from './transport.ts';

/** The name the route has always used for the orphan stop-directive part. */
const STOP_DIRECTIVE_NAME = '__system_stop_directive__';

/* ─── Request ───────────────────────────────────────────────── */

function toolResultPart(item: ToolResultItem): GeminiPart {
  if (item.kind === 'directive') {
    return {
      functionResponse: {
        name: STOP_DIRECTIVE_NAME,
        response: { stop_directive: item.text },
      },
    };
  }
  return {
    functionResponse: {
      name: item.name,
      response: item.payload,
    },
  };
}

function toGeminiContent(message: TurnMessage): GeminiContent {
  switch (message.role) {
    case 'user':
      return { role: 'user', parts: [{ text: message.text }] };
    case 'assistant':
      return { role: 'model', parts: [{ text: message.text }] };
    case 'assistant_turn':
      // Replayed verbatim: the native parts keep any thought signatures.
      return { role: 'model', parts: message.turn.raw as GeminiPart[] };
    case 'tool_results':
      return { role: 'user', parts: message.items.map(toolResultPart) };
  }
}

/**
 * One tool in Gemini's function-declaration form. Sanitizing a schema is the
 * expensive part of building a request (it walks and inlines `$ref`s), and the
 * route reuses the same `ToolSpec` objects across calls and across requests
 * (its MCP tool list is cached), so the rendered declaration is cached per
 * spec object. Specs are treated as immutable once built.
 */
export interface GeminiFunctionDeclaration {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

const declarationCache = new WeakMap<ToolSpec, GeminiFunctionDeclaration>();

export function geminiFunctionDeclarations(tools: ToolSpec[]): GeminiFunctionDeclaration[] {
  return tools.map((tool) => {
    let declaration = declarationCache.get(tool);
    if (!declaration) {
      declaration = {
        name: tool.name,
        description: tool.description,
        // toGeminiSchema edits `properties` in place; sanitize a copy so the
        // caller's tool specs stay untouched.
        parameters: toGeminiSchema(structuredClone(tool.inputSchema || {})),
      };
      declarationCache.set(tool, declaration);
    }
    return declaration;
  });
}

/**
 * The request's `tools` member. 'none' keeps today's summarize and
 * budget-summary payloads (`tools: []`); anything else is one group holding
 * every declaration.
 */
export function buildGeminiToolsParam(
  tools: ToolSpec[],
  toolChoice: ModelRequest['toolChoice'],
): GeminiCallPayload['tools'] {
  if (toolChoice === 'none') return [];
  return [{ functionDeclarations: geminiFunctionDeclarations(tools) }];
}

/** Neutral request -> the Gemini JSON body. Pure; does not mutate `req`. */
export function buildGeminiRequestPayload(req: ModelRequest): GeminiCallPayload {
  return buildGeminiPayload({
    contents: req.messages.map(toGeminiContent),
    tools: buildGeminiToolsParam(req.tools, req.toolChoice),
    systemText: req.system,
    thinking: req.thinking,
    forceToolUse: req.toolChoice === 'required',
  });
}

/* ─── Response ──────────────────────────────────────────────── */

interface GeminiResponseShape {
  candidates?: Array<{
    content?: { parts?: GeminiPart[] };
    finishReason?: string;
  }>;
  usageMetadata?: Record<string, unknown>;
  responseId?: unknown;
}

function mapFinish(finishReason: string | undefined, hasToolCalls: boolean): FinishReason {
  if (finishReason === 'MAX_TOKENS') return 'max_tokens';
  if (finishReason === 'SAFETY') return 'safety';
  if (finishReason === 'RECITATION') return 'recitation';
  if (hasToolCalls) return 'tool_use';
  if (finishReason === 'STOP') return 'stop';
  return 'other';
}

function numberOrZero(value: unknown): number {
  return typeof value === 'number' ? value : 0;
}

function mapUsage(usage: Record<string, unknown> | undefined): NeutralUsage | null {
  if (!usage) return null;
  // Gemini reports thinking tokens beside the answer tokens, not inside them
  // (`candidatesTokenCount` excludes `thoughtsTokenCount`), and bills both at
  // the output rate. Claude's and OpenAI's output counts already include their
  // reasoning, so the neutral `output` is the billed total here too and
  // `reasoning` stays the informational subset of it.
  const thoughts = numberOrZero(usage['thoughtsTokenCount']);
  return {
    inputTotal: numberOrZero(usage['promptTokenCount']),
    cacheRead: numberOrZero(usage['cachedContentTokenCount']),
    cacheWrite: 0,
    cacheWrite1h: 0,
    output: numberOrZero(usage['candidatesTokenCount']) + thoughts,
    reasoning: thoughts,
  };
}

/** Gemini `generateContent` JSON -> neutral turn. `step` numbers the call ids. */
export function parseGeminiResponse(
  response: GeminiResponseShape,
  info: { model: string; step: number; decodeName?: (wire: string) => string | undefined },
): AssistantTurn {
  const candidate = response.candidates?.[0];
  const parts: GeminiPart[] = candidate?.content?.parts || [];
  const text: string[] = [];
  const thinking: string[] = [];
  const toolCalls: AssistantTurn['toolCalls'] = [];
  let leaked = false;
  for (const part of parts) {
    if (part.text) {
      if (part.thought === true) {
        thinking.push(part.text);
        // `default_api` is Gemini's function-call namespace marker and never
        // appears in legitimate reasoning prose.
        if (!leaked && /default_api/.test(part.text)) leaked = true;
      } else {
        text.push(part.text);
      }
    }
    if (part.functionCall) {
      toolCalls.push({
        id: `gem_${info.step}_${toolCalls.length}`,
        // Gemini's names are canonical (identity codec); a decoder that does
        // not recognise a name leaves it as the model wrote it.
        name: info.decodeName?.(part.functionCall.name) ?? part.functionCall.name,
        args: part.functionCall.args || {},
      });
    }
  }
  const turn: AssistantTurn = {
    provider: 'vertex',
    model: info.model,
    text,
    thinking,
    toolCalls,
    finish: mapFinish(candidate?.finishReason, toolCalls.length > 0),
    finishDetail: candidate?.finishReason,
    usage: mapUsage(response.usageMetadata),
    leakedToolCallSuspected: leaked,
    raw: parts,
  };
  if (typeof response.responseId === 'string') turn.requestId = response.responseId;
  return turn;
}

/* ─── Errors ────────────────────────────────────────────────── */

/**
 * Map a transport error (the route throws `Gemini API error: <status> <body>`
 * and `Vertex AI error: <status> <body>`) onto a `ProviderError`. Request and
 * response bodies are not copied beyond the redacted message.
 */
export function classifyGeminiError(err: unknown): ProviderError {
  if (err instanceof ProviderError) return err;
  const message = err instanceof Error ? err.message : String(err);
  const match = /(?:Gemini API|Vertex AI) error: (\d{3})/.exec(message);
  const status = match ? Number(match[1]) : undefined;
  const base = { message: redactSecrets(message), status, cause: err };
  if (status === undefined) {
    const network = /fetch failed|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|network/i.test(message);
    return new ProviderError({ kind: network ? 'network' : 'unknown', retryable: network, ...base });
  }
  if (status === 429) return new ProviderError({ kind: 'rate_limit', retryable: true, ...base });
  if (status === 401 || message.includes('API_KEY_INVALID') || message.includes('API key not valid')) {
    return new ProviderError({ kind: 'auth', ...base });
  }
  if (status === 403) return new ProviderError({ kind: 'permission', ...base });
  if (status === 404) return new ProviderError({ kind: 'model_not_found', ...base });
  if (status === 400) {
    const tooLong = /token count|exceeds the maximum|context window/i.test(message);
    return new ProviderError({ kind: tooLong ? 'context_exceeded' : 'invalid_request', ...base });
  }
  if (status === 503) return new ProviderError({ kind: 'overloaded', retryable: false, ...base });
  if (status >= 500) return new ProviderError({ kind: 'unavailable', ...base });
  return new ProviderError({ kind: 'unknown', ...base });
}

/* ─── Adapter ───────────────────────────────────────────────── */

function toGeminiCredentials(creds: ProviderCreds) {
  return {
    GEMINI_API_KEY: creds.apiKey,
    GOOGLE_APPLICATION_CREDENTIALS: creds.serviceAccountJson,
  };
}

/** Keeps each entry point's existing "no provider" wording. */
function noProviderMessage(purpose: ModelRequest['purpose']): string {
  if (purpose === 'subagent') return GEMINI_NO_PROVIDER_MESSAGES.subagent;
  if (purpose === 'summarize' || purpose === 'plan') return GEMINI_NO_PROVIDER_MESSAGES.summarize;
  return GEMINI_NO_PROVIDER_MESSAGES.chat;
}

const GEMINI_CAPABILITIES: AdapterCapabilities = { leakRecovery: true, emptyTurnRetry: true };

export function createGeminiAdapter(deps: GeminiTransportDeps = {}): ProviderAdapter {
  return {
    id: 'vertex',
    capabilities: GEMINI_CAPABILITIES,

    estimateToolsPayload(tools: ToolSpec[]) {
      return buildGeminiToolsParam(tools, 'auto');
    },

    // Transport errors propagate unchanged, as they do from the route today;
    // `classifyError` converts them where a caller wants the neutral kind.
    async call(req: ModelRequest, ctx: CallContext): Promise<AssistantTurn> {
      // Identity codec: Gemini keeps dotted names and the catalog unchanged.
      const codec = buildToolNameCodec(req.tools, 'identity');
      const payload = buildGeminiRequestPayload({ ...req, tools: codec.tools });
      if (ctx.signal?.aborted) throw abortedError();
      let response;
      try {
        response = await callGeminiGenerateContent(
          payload,
          toGeminiCredentials(ctx.creds),
          req.ref.model,
          noProviderMessage(req.purpose),
          ctx.signal ? { ...deps, signal: ctx.signal } : deps,
        );
      } catch (err) {
        // A cancelled request rejects with a bare AbortError; give it the same
        // neutral shape the other adapters throw so callers can end quietly.
        if (ctx.signal?.aborted) throw abortedError();
        throw err;
      }
      return parseGeminiResponse(response, {
        model: req.ref.model,
        step: ctx.step ?? 0,
        decodeName: codec.decode,
      });
    },

    // Not wired in this stage: the Gemini model list is curated, and the
    // registry that owns it arrives with the registry work. Returning an
    // empty list is honest (nothing live was fetched).
    async listModels(): Promise<LiveModel[]> {
      return [];
    },

    // Not wired in this stage: the connection test is served by the existing
    // /api/agent/providers/vertex/test route.
    async testConnection() {
      return {
        ok: false,
        message: 'Connection testing for this provider is served by /api/agent/providers/vertex/test.',
      };
    },

    classifyError: classifyGeminiError,
  };
}
