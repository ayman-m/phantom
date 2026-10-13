/**
 * Provider-neutral model types.
 *
 * Every model provider adapter (Gemini today; others later) converts between
 * these neutral shapes and its own wire format, so the chat route can run one
 * tool loop over any provider.
 *
 * Erasable TypeScript only (no enums, namespaces or parameter properties) and
 * no runtime imports (the one import below is type-only and erased), so
 * Node's type stripping can load this file in unit tests.
 */

import type { ProviderError } from './errors.ts';

export type ProviderId = 'vertex' | 'anthropic' | 'openai';

/** Canonical string form is "provider/model". */
export interface ModelRef {
  provider: ProviderId;
  model: string;
}

/** A tool as the route knows it. `name` is the canonical (MCP) name. */
export interface ToolSpec {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export type ToolResultItem =
  // payload is `{result}` or `{error, ...}`
  | { kind: 'result'; callId: string; name: string; payload: Record<string, unknown> }
  // A system instruction injected beside the tool results (was the orphan
  // `__system_stop_directive__` function response).
  | { kind: 'directive'; text: string };

export type TurnMessage =
  | { role: 'user'; text: string }
  // Replayed history: cross-turn history is plain text for every provider.
  | { role: 'assistant'; text: string }
  // In-loop assistant output; replayed through `turn.raw`.
  | { role: 'assistant_turn'; turn: AssistantTurn }
  // Ordered results for the calls of the preceding assistant_turn.
  | { role: 'tool_results'; items: ToolResultItem[] };

export type FinishReason =
  | 'stop'
  | 'tool_use'
  | 'max_tokens'
  | 'safety'
  | 'recitation'
  | 'refusal'
  | 'context_exceeded'
  | 'other';

export interface NeutralUsage {
  /** ALL input tokens, including cache reads and writes (normalized). */
  inputTotal: number;
  cacheRead: number;
  /** ALL cache-write tokens, 5-minute and 1-hour together. */
  cacheWrite: number;
  /** The 1-hour subset of `cacheWrite`; the 5-minute portion is `cacheWrite - cacheWrite1h`. */
  cacheWrite1h: number;
  /**
   * ALL billed output tokens, reasoning included. Claude and OpenAI report it
   * that way; the Gemini adapter adds `thoughtsTokenCount` to
   * `candidatesTokenCount` to match. Cost is `output` at the output rate, so
   * `reasoning` must never be added to it again.
   */
  output: number;
  /** The reasoning tokens inside `output`; informational, never billed separately. */
  reasoning: number;
}

export interface AssistantTurn {
  provider: ProviderId;
  model: string;
  text: string[];
  thinking: string[];
  toolCalls: ToolCall[];
  finish: FinishReason;
  /** The provider's own finish string, kept so callers can branch on it. */
  finishDetail?: string;
  usage: NeutralUsage | null;
  requestId?: string;
  /** Gemini: a function call was serialized into a thought part. Others: false. */
  leakedToolCallSuspected: boolean;
  /** Provider-native assistant payload, replayed verbatim inside a turn. */
  raw: unknown;
}

export interface ModelRequest {
  ref: ModelRef;
  system: string;
  messages: TurnMessage[];
  tools: ToolSpec[];
  toolChoice: 'auto' | 'required' | 'none';
  thinking: boolean;
  purpose: 'chat' | 'subagent' | 'summarize' | 'plan' | 'budget_summary';
  /** Session-derived key for providers that support prompt-cache routing. */
  cacheKey?: string;
}

/** Credentials handed to an adapter explicitly; adapters never read env. */
export interface ProviderCreds {
  apiKey?: string;
  /** Vertex: service-account JSON text, or a key-file path. */
  serviceAccountJson?: string;
  baseUrl?: string;
  organization?: string;
  project?: string;
}

/**
 * A non-fatal observation an adapter makes while serving a call: a request
 * setting it had to change (`tool_choice_downgraded`), or model output it had
 * to drop (`tool_call_truncated`). The caller decides whether to log, stream
 * or ignore it.
 */
export interface ProviderEvent {
  type: string;
  message: string;
  data?: Record<string, unknown>;
}

/** Per-call context. */
export interface CallContext {
  creds: ProviderCreds;
  /** Position of this call within the turn; used to synthesize call ids. */
  step?: number;
  signal?: AbortSignal;
  /** Receives adapter observations; absent means they are dropped. */
  onEvent?: (event: ProviderEvent) => void;
}

/** Thinking and effort capabilities a live list may report for a model. */
export interface LiveCapabilities {
  thinkingAdaptive?: boolean;
  thinkingEnabled?: boolean;
  /** False exactly when `thinking: {type: "disabled"}` would be rejected. */
  thinkingDisabled?: boolean;
  /** Effort levels the model accepts. */
  efforts?: string[];
}

/** A model as reported by a provider's live list endpoint. */
export interface LiveModel {
  id: string;
  displayName?: string;
  contextWindow?: number;
  maxOutput?: number;
  /** Largest accepted prompt, when the provider reports it below the window. */
  maxInput?: number;
  /** ISO timestamp of the announced retirement. */
  retiresAt?: string;
  /** The provider's own lifecycle word, when it reports one. */
  lifecycle?: 'active' | 'deprecated' | 'retired';
  capabilities?: LiveCapabilities;
}

export type ProviderErrorKind =
  | 'rate_limit'
  | 'overloaded'
  | 'quota_exhausted'
  | 'auth'
  | 'permission'
  | 'invalid_request'
  | 'context_exceeded'
  | 'model_not_found'
  | 'unavailable'
  | 'network'
  | 'unknown';

/**
 * What the route's tool loop may rely on per provider. Both flags are Gemini
 * behaviours: a thinking model can serialize a pending call into a thought
 * part (leak recovery), and an intermittent empty turn is worth one retry
 * (empty-turn retry). Other providers leave them off.
 */
export interface AdapterCapabilities {
  leakRecovery: boolean;
  emptyTurnRetry: boolean;
}

export interface ProviderAdapter {
  id: ProviderId;
  capabilities: AdapterCapabilities;
  call(req: ModelRequest, ctx: CallContext): Promise<AssistantTurn>;
  /**
   * The provider-rendered tool catalog, as the request payload would carry
   * it. The context guard estimates tokens from this, so the estimate tracks
   * what is actually sent. Absent: callers fall back to the neutral specs.
   */
  estimateToolsPayload?(tools: ToolSpec[]): unknown;
  listModels(creds: ProviderCreds, signal: AbortSignal): Promise<LiveModel[]>;
  /** `status` is the provider's HTTP status when it answered, for the audit row. */
  testConnection(creds: ProviderCreds): Promise<{ ok: boolean; message: string; modelCount?: number; status?: number }>;
  classifyError(err: unknown): ProviderError;
}
