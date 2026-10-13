/**
 * The one entry point the chat route uses to reach a model.
 *
 * `callModel` picks the adapter for the request's provider and hands it the
 * neutral request plus explicit credentials; the adapter owns the wire format.
 * `summarizeText` is the tool-less one-shot used by /compress, /plan and
 * auto-compaction.
 *
 * One adapter exists per provider: Gemini (`vertex`), Claude (`anthropic`) and
 * OpenAI (`openai`). The caller's credentials are Google's, so they reach only
 * the Vertex adapter; every other provider reads its own stored credentials
 * (and a provider with none stored fails through the single
 * `PROVIDER_NOT_CONFIGURED` path). Errors from an adapter propagate
 * unchanged, so the three entry-point wordings of the Gemini "no provider"
 * message (chat, subagent, summarizer) are still produced by the adapter from
 * `req.purpose`.
 *
 * Credentials come in as arguments, and which model a turn runs on is decided
 * by model-resolution.ts before a request is built; this module reads no
 * environment and has no `@/` imports, so it loads under Node's type stripping.
 *
 * Erasable TypeScript only.
 */

import { createAnthropicAdapter } from './anthropic/adapter.ts';
import { resolveProviderCreds } from './credentials.ts';
import { ProviderError } from './errors.ts';
import { createGeminiAdapter } from './gemini/adapter.ts';
import { createOpenAiAdapter } from './openai/adapter.ts';
import type {
  AssistantTurn,
  ModelRef,
  ModelRequest,
  ProviderAdapter,
  ProviderCreds,
  ProviderEvent,
  ProviderId,
  ToolSpec,
} from './types.ts';

/** The two credential fields the runtime config carries for Gemini. */
export interface GeminiRuntimeCredentials {
  GEMINI_API_KEY?: string;
  GOOGLE_APPLICATION_CREDENTIALS?: string;
}

export function credsFromRuntimeConfig(runtimeConfig: GeminiRuntimeCredentials): ProviderCreds {
  return {
    apiKey: runtimeConfig.GEMINI_API_KEY,
    serviceAccountJson: runtimeConfig.GOOGLE_APPLICATION_CREDENTIALS,
  };
}

export interface DispatchDeps {
  /** Adapters by provider; absent entries fall back to the built-in adapter. */
  adapters?: Partial<Record<ProviderId, ProviderAdapter>>;
  /**
   * The stored credentials of a provider other than Vertex; defaults to the
   * ProviderStore reader. Null means the provider is not configured.
   */
  resolveCreds?: (provider: ProviderId) => Promise<ProviderCreds | null>;
  /**
   * Hosts a provider base URL may not point at (the MCP host), handed to the
   * Claude and OpenAI adapters the dispatcher creates. The chat route passes
   * the same list the Providers page and the connection tests use; without it
   * a stored gateway URL that names the MCP would be reachable from chat.
   */
  blockedHosts?: readonly string[];
}

let builtinGemini: ProviderAdapter | null = null;
// Keyed by the blocked-host list, so a different list gets its own adapter.
const builtinAnthropic = new Map<string, ProviderAdapter>();
const builtinOpenAi = new Map<string, ProviderAdapter>();

export function resolveAdapter(ref: ModelRef, deps: DispatchDeps = {}): ProviderAdapter {
  const injected = deps.adapters?.[ref.provider];
  if (injected) return injected;
  if (ref.provider === 'vertex') {
    builtinGemini ??= createGeminiAdapter();
    return builtinGemini;
  }
  const blockedHosts = deps.blockedHosts ?? [];
  const key = blockedHosts.join('\n');
  if (ref.provider === 'anthropic') {
    let adapter = builtinAnthropic.get(key);
    if (!adapter) builtinAnthropic.set(key, (adapter = createAnthropicAdapter({ blockedHosts })));
    return adapter;
  }
  if (ref.provider === 'openai') {
    let adapter = builtinOpenAi.get(key);
    if (!adapter) builtinOpenAi.set(key, (adapter = createOpenAiAdapter({ blockedHosts })));
    return adapter;
  }
  // Unreachable for a typed ProviderId; guards a ref built from untyped input.
  throw new ProviderError({
    kind: 'invalid_request',
    code: 'PROVIDER_NOT_CONFIGURED',
    message: `The "${String(ref.provider)}" model provider is not known to this build.`,
  });
}

export interface CallOptions {
  creds: ProviderCreds;
  /**
   * Position of this call within the turn. Adapters that must synthesize call
   * ids (Gemini returns none) derive them from it, so it has to increase for
   * every call in one turn, retries included.
   */
  step?: number;
  signal?: AbortSignal;
  /** Receives adapter observations such as `tool_choice_downgraded`. */
  onEvent?: (event: ProviderEvent) => void;
}

const PROVIDER_NAMES: Record<ProviderId, string> = {
  vertex: 'Google',
  anthropic: 'Anthropic',
  openai: 'OpenAI',
};

/**
 * Credentials for a provider other than Vertex always come from that
 * provider's own stored instance. `opts.creds` is the caller's Google
 * credential set, and handing it to another vendor would send it there as a
 * bearer token.
 */
async function storedCreds(provider: ProviderId, deps: DispatchDeps): Promise<ProviderCreds> {
  const creds = await (deps.resolveCreds ?? resolveProviderCreds)(provider);
  if (!creds) {
    throw new ProviderError({
      kind: 'auth',
      code: 'PROVIDER_NOT_CONFIGURED',
      message: `No ${PROVIDER_NAMES[provider]} API key is configured. Add the provider on the Providers page, then try again.`,
    });
  }
  return creds;
}

export async function callModel(
  req: ModelRequest,
  opts: CallOptions,
  deps: DispatchDeps = {},
): Promise<AssistantTurn> {
  const adapter = resolveAdapter(req.ref, deps);
  const creds = req.ref.provider === 'vertex' ? opts.creds : await storedCreds(req.ref.provider, deps);
  return await adapter.call(req, { creds, step: opts.step, signal: opts.signal, onEvent: opts.onEvent });
}

/** What the adapter's capabilities allow the tool loop to rely on. */
export function capabilitiesFor(ref: ModelRef, deps: DispatchDeps = {}) {
  return resolveAdapter(ref, deps).capabilities;
}

/**
 * The tool catalog as the provider would put it on the wire, serialized for
 * token estimation. Falls back to the neutral specs for an adapter that has no
 * rendering of its own.
 */
export function estimateToolsJson(
  ref: ModelRef,
  tools: ToolSpec[],
  deps: DispatchDeps = {},
): string {
  const adapter = resolveAdapter(ref, deps);
  return JSON.stringify(adapter.estimateToolsPayload ? adapter.estimateToolsPayload(tools) : tools);
}

/**
 * One-shot, tool-less completion: a system instruction plus one user message,
 * answered with text. No agent persona, no history, no tools, no thinking.
 */
export async function summarizeText(
  ref: ModelRef,
  system: string,
  userContent: string,
  purpose: 'summarize' | 'plan',
  opts: CallOptions,
  deps: DispatchDeps = {},
): Promise<string> {
  const turn = await callModel(
    {
      ref,
      system,
      messages: [{ role: 'user', text: userContent }],
      tools: [],
      toolChoice: 'none',
      thinking: false,
      purpose,
    },
    opts,
    deps,
  );
  return turn.text.join('').trim();
}
