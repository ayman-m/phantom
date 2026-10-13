/**
 * Gemini request payload: wire types and the one place a payload is assembled.
 *
 * The types and `GeminiCallPayload` are moved verbatim from the chat route.
 * `buildGeminiPayload` is the assembly that `callGemini`, `callGeminiRaw` and
 * `summarizeViaGemini` each did inline; the key order below is part of the
 * wire contract (the parity fixtures compare `JSON.stringify` output byte for
 * byte): contents, tools, systemInstruction, generationConfig, toolConfig.
 *
 * Erasable TypeScript only; no imports.
 */

export type GeminiFunctionCall = {
  name: string;
  args?: Record<string, unknown>;
};

export type GeminiPart = {
  text?: string;
  // Set to `true` by Gemini when the part is reasoning output
  // (engaged by generationConfig.thinkingConfig.includeThoughts = true).
  // The chat route emits these via the SSE `thinking` event instead of
  // `text_delta`, and they're excluded from the saved `.content` so the
  // operator's transcript shows reasoning collapsed-by-default and the
  // final answer cleanly.
  thought?: boolean;
  functionCall?: GeminiFunctionCall;
  functionResponse?: {
    name: string;
    response: Record<string, unknown>;
  };
};

export type GeminiSystemInstruction = {
  role: 'system';
  parts: Array<{ text: string }>;
};

export type GeminiContent = {
  role: 'user' | 'model';
  parts: GeminiPart[];
};

export type GeminiCallPayload = {
  contents: GeminiContent[];
  tools: Array<{ functionDeclarations: unknown }>;
  systemInstruction?: GeminiSystemInstruction;
  // GenerationConfig is optional with no default fields. A hardcoded
  // `maxOutputTokens` (e.g. 4096) would cap Gemini's output at a small
  // fraction of the model's natural ceiling (~65K tokens for
  // gemini-3.1-pro-preview), and multi-step responses with rich
  // tool-output narration would truncate mid-sentence. The caller can
  // override via an optional explicit maxOutputTokens; default = unset
  // = let Gemini use the model max.
  generationConfig?: {
    maxOutputTokens?: number;
    // Extended thinking. When the caller passes `thinking: true`,
    // callGemini sets thinkingConfig here with `thinkingBudget: -1`
    // (Gemini's "use what you need" signal). Models without thinking
    // support ignore it.
    thinkingConfig?: {
      thinkingBudget: number;
      includeThoughts?: boolean;
    };
  };
  // Forced function-calling. mode:'ANY' makes Gemini MUST
  // return a functionCall part (no text-only / thought-only turn). Used by
  // the leaked-tool-call recovery path: when a thinking model
  // serializes a large tool call as `thought` text instead of a structured
  // functionCall (dropping it + ending the turn), we retry with mode:'ANY'
  // + thinking off to force a clean structured call.
  toolConfig?: {
    functionCallingConfig: {
      mode: 'AUTO' | 'ANY' | 'NONE';
    };
  };
};

export interface BuildGeminiPayloadArgs {
  contents: GeminiContent[];
  tools: Array<{ functionDeclarations: unknown }>;
  /** The full system prompt text; wrapped into `systemInstruction`. */
  systemText: string;
  /** Extended thinking: adds generationConfig.thinkingConfig. */
  thinking?: boolean;
  /** Force a structured functionCall: adds toolConfig mode 'ANY'. */
  forceToolUse?: boolean;
}

export function buildGeminiPayload(args: BuildGeminiPayloadArgs): GeminiCallPayload {
  const systemInstruction: GeminiSystemInstruction = {
    role: 'system',
    parts: [{ text: args.systemText }],
  };
  return {
    contents: args.contents,
    tools: args.tools,
    systemInstruction,
    // No maxOutputTokens cap; Gemini uses model's natural max.
    ...(args.thinking
      ? {
          generationConfig: {
            thinkingConfig: {
              thinkingBudget: -1, // -1 = "use what you need" (Gemini API).
              includeThoughts: true,
            },
          },
        }
      : {}),
    // Force a structured functionCall on the recovery retry.
    ...(args.forceToolUse
      ? { toolConfig: { functionCallingConfig: { mode: 'ANY' as const } } }
      : {}),
  };
}
