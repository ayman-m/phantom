/**
 * Phantom model catalog — returns the Vertex AI / Gemini models that
 * phantom standalone supports today, plus placeholder entries for the
 * other providers (Anthropic, OpenAI) that are WIP.
 *
 * Spark's workspace exposes /api/v1/models via its api-gateway, which
 * dynamically discovers models from each connected provider. Phantom
 * is single-tenant and currently only ships Vertex AI integration in
 * the chat code path, so we serve a curated catalog from this route
 * rather than probing remote model APIs at request time.
 *
 * Shape matches Spark's ModelInfo (lib/api/types.ts) so the ported
 * /models page renders without adapter glue.
 */

import { NextResponse } from "next/server";
import { getEffectiveRuntimeConfig } from "@/lib/runtime-config";
import { resolveAnthropicApiKey } from "@/lib/anthropic-credentials";

export const dynamic = "force-dynamic";

// Trimmed `ModelInfo` shape — just the fields the /models page reads.
interface ModelInfo {
  provider: string;
  model: string;
  displayName?: string;
  kind?: "chat" | "embedding" | "image" | "voice";
  contextWindow: number;
  supportsThinking?: boolean;
  supportsTools?: boolean;
  interactionPatterns?: ("streaming_api" | "cli_tool" | "async_job" | "interactive_session")[];
  launchStage?: "GA" | "PUBLIC_PREVIEW" | "PRIVATE_PREVIEW" | "EXPERIMENTAL";
  // Coming-soon flag. See lib/api/types.ts ModelInfo.wip.
  wip?: boolean;
}

// Phantom's curated Vertex catalog. Updated when Google ships new
// generations. Context windows reflect the published Vertex docs at
// the time of writing.
const VERTEX_MODELS: ModelInfo[] = [
  // ── Chat (Gemini 3 family) ──────────────────────────────────────
  // Gemini 3.7 Flash, the current Flash-tier flagship. Listed FIRST
  // so it is the default Flash choice in the model picker.
  //
  // Every model must be listed here AND in lib/model-context-caps.ts:
  // this catalog is what the picker serves, so a model absent here is
  // unselectable no matter what the caps map says.
  {
    provider: "vertex",
    model: "gemini-3.7-flash",
    displayName: "Gemini 3.7 Flash",
    kind: "chat",
    contextWindow: 1_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  // Gemini 3.5 Flash. Released at Google I/O 2026 (May
  // 19-20); GA on Vertex AI with global + regional endpoints. Coding
  // and reasoning quality close to Gemini Pro at Flash speed and
  // cost (~$1.50 / $9 per 1M tokens). Default thinking effort is
  // medium per the model card. There is no Gemini 3.5 Pro yet —
  // Google released only the Flash tier at I/O 2026.
  {
    provider: "vertex",
    model: "gemini-3.5-flash",
    displayName: "Gemini 3.5 Flash",
    kind: "chat",
    contextWindow: 1_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  {
    provider: "vertex",
    model: "gemini-3.1-pro-preview",
    displayName: "Gemini 3.1 Pro",
    kind: "chat",
    contextWindow: 2_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "PUBLIC_PREVIEW",
  },
  {
    provider: "vertex",
    model: "gemini-3.0-pro",
    displayName: "Gemini 3.0 Pro",
    kind: "chat",
    contextWindow: 2_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  {
    provider: "vertex",
    model: "gemini-2.5-pro",
    displayName: "Gemini 2.5 Pro",
    kind: "chat",
    contextWindow: 2_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  {
    provider: "vertex",
    model: "gemini-2.5-flash",
    displayName: "Gemini 2.5 Flash",
    kind: "chat",
    contextWindow: 1_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  {
    provider: "vertex",
    model: "gemini-2.5-flash-lite",
    displayName: "Gemini 2.5 Flash Lite",
    kind: "chat",
    contextWindow: 1_000_000,
    supportsThinking: false,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  // ── Embedding ───────────────────────────────────────────────────
  {
    provider: "vertex",
    model: "gemini-embedding-001",
    displayName: "Gemini Embedding",
    kind: "embedding",
    contextWindow: 8_192,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  {
    provider: "vertex",
    model: "text-embedding-005",
    displayName: "text-embedding-005",
    kind: "embedding",
    contextWindow: 2_048,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
  },
  // ── Image generation ────────────────────────────────────────────
  {
    provider: "vertex",
    model: "imagen-4.0-generate-preview",
    displayName: "Imagen 4",
    kind: "image",
    contextWindow: 0,
    interactionPatterns: ["async_job"],
    launchStage: "PUBLIC_PREVIEW",
  },
  {
    provider: "vertex",
    model: "imagen-3.0-generate-002",
    displayName: "Imagen 3",
    kind: "image",
    contextWindow: 0,
    interactionPatterns: ["async_job"],
    launchStage: "GA",
  },
  // ── Voice (TTS / STT) ───────────────────────────────────────────
  {
    provider: "vertex",
    model: "chirp-3-hd",
    displayName: "Chirp 3 HD (TTS)",
    kind: "voice",
    contextWindow: 0,
    interactionPatterns: ["streaming_api"],
    launchStage: "PUBLIC_PREVIEW",
  },
];

// Anthropic / Claude catalog. It lets the /models page
// surface Claude entries when an Anthropic provider is configured
// (anthropicApiKey).
//
// Every Anthropic entry ships with `wip: true`. The
// chat header's model dropdown filters wip entries out (operators
// can't accidentally route to a path we haven't fully validated yet).
// The /services Models page still surfaces them, just rendered with
// a greyed-out "Coming soon" treatment so the roadmap is visible.
// To re-enable Claude as a chat-selectable target, drop the wip flag
// on the relevant entries.
//
// Context windows + thinking flags reflect Anthropic's public model card
// at the time of writing. Update when Anthropic ships new generations.
const ANTHROPIC_MODELS: ModelInfo[] = [
  // ── Chat (Claude 4.x family, streaming_api path) ────────────────
  {
    provider: "anthropic",
    model: "claude-opus-4-7-20260415",
    displayName: "Claude Opus 4.7 (1M context)",
    kind: "chat",
    contextWindow: 1_000_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
    wip: true,
  },
  {
    provider: "anthropic",
    model: "claude-sonnet-4-6-20260213",
    displayName: "Claude Sonnet 4.6",
    kind: "chat",
    contextWindow: 200_000,
    supportsThinking: true,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
    wip: true,
  },
  {
    provider: "anthropic",
    model: "claude-haiku-4-5-20260129",
    displayName: "Claude Haiku 4.5",
    kind: "chat",
    contextWindow: 200_000,
    supportsThinking: false,
    supportsTools: true,
    interactionPatterns: ["streaming_api"],
    launchStage: "GA",
    wip: true,
  },
];

export async function GET() {
  // `vertexConfigured` must be derived from the fields that exist on the
  // EffectiveRuntimeConfig type (not `cfg.vertexProjectId` /
  // `cfg.vertexServiceAccountJson`, which don't exist and would be silently
  // undefined at runtime, making the route always return []).
  //
  // The correct signal: `GOOGLE_APPLICATION_CREDENTIALS` is populated
  // by `getEffectiveRuntimeConfig()` from
  // `resolveVertexCredentialsFromStore()` (returns the SA JSON content
  // when a vertex provider instance exists in ProviderStore), with an
  // env fallback. If THAT field is non-empty, Vertex is configured.
  //
  // Companion check: `GEMINI_API_KEY` — alternative auth path. Either
  // populates the same underlying Gemini model catalog.
  //
  // Anthropic catalog. The /models page and the chat header's model
  // dropdown surface Claude entries when an Anthropic provider is
  // configured, so the catalog must not be Vertex-only.
  //
  // Anthropic credential resolution mirrors `lib/anthropic-credentials.ts`:
  // an API key (provider store, else the ANTHROPIC_API_KEY env var).
  const [cfg, anthropicApiKey] = await Promise.all([
    getEffectiveRuntimeConfig(),
    resolveAnthropicApiKey(),
  ]);
  const vertexConfigured = Boolean(
    cfg.GOOGLE_APPLICATION_CREDENTIALS &&
      cfg.GOOGLE_APPLICATION_CREDENTIALS.trim(),
  );
  const geminiKeyConfigured = Boolean(
    cfg.GEMINI_API_KEY && cfg.GEMINI_API_KEY.trim(),
  );
  const anthropicConfigured = Boolean(anthropicApiKey);

  const models: ModelInfo[] = [
    ...(vertexConfigured || geminiKeyConfigured ? VERTEX_MODELS : []),
    ...(anthropicConfigured ? ANTHROPIC_MODELS : []),
  ];
  return NextResponse.json(models);
}
