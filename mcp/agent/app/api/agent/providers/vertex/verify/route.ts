/**
 * POST /api/agent/providers/vertex/verify
 *
 * The "Verify" action on /models/[model]: does this Gemini model exist and is
 * it enabled for the configured credentials? Vertex has no usable model list,
 * so the registry cannot prove it; this asks the provider with `:countTokens`
 * (no generation, no cost).
 *
 * Body (JSON):  { model: "gemini-3.1-pro-preview" }  (an optional "vertex/"
 * prefix is accepted). Only chat models in the registry's Vertex catalog may be
 * probed.
 *
 * Response, always HTTP 200 like vertex/test:
 *   { status: "success" | "error", message, via: "gemini-api" | "vertex" | null }
 *
 * Under /api/agent/providers, so API keys are refused with 403 (the
 * credential-route guardrail in lib/agent-scopes.ts). Credentials are read
 * server-side and never returned.
 */

import { NextResponse } from "next/server";

import { getEffectiveRuntimeConfig } from "@/lib/runtime-config";
import { verifyGeminiModel } from "@/lib/providers/gemini/verify";
import { CURATED_CATALOG } from "@/lib/providers/registry/lookup";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let body: { model?: unknown };
  try {
    body = (await request.json()) as { model?: unknown };
  } catch {
    return NextResponse.json({ status: "error", message: "Request body must be valid JSON.", via: null });
  }
  const raw = typeof body.model === "string" ? body.model.trim() : "";
  const model = raw.replace(/^vertex\//i, "");
  const known = CURATED_CATALOG.find(
    (m) => m.provider === "vertex" && m.kind === "chat" && m.model === model,
  );
  if (!known) {
    return NextResponse.json({
      status: "error",
      message: `${raw || "That"} is not a Gemini chat model in the catalog.`,
      via: null,
    });
  }
  const cfg = await getEffectiveRuntimeConfig();
  const result = await verifyGeminiModel(
    {
      apiKey: cfg.GEMINI_API_KEY || undefined,
      serviceAccountJson: cfg.GOOGLE_APPLICATION_CREDENTIALS || undefined,
    },
    known.model,
  );
  return NextResponse.json({
    status: result.ok ? "success" : "error",
    message: result.message,
    via: result.via,
  });
}
