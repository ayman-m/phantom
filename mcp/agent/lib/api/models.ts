import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { ModelInfo, ModelStats } from "./types";

/** List available models from GET /api/v1/models. */
export function listModels(options?: ApiRequestOptions) {
  return listRequest<ModelInfo>("/api/v1/models", options);
}

/** Get a single model by provider and model ID. */
export async function getModel(
  provider: string,
  modelId: string,
  options?: ApiRequestOptions,
) {
  const result = await listModels(options);
  if (!result.ok) return result;
  const found = result.data.find(
    (m) => m.provider === provider && m.model === modelId,
  );
  if (!found) {
    return {
      ok: false as const,
      error: { code: "NOT_FOUND", message: `Model ${modelId} not found` },
    };
  }
  return { ok: true as const, data: found };
}

/** Options for fetching model usage stats. */
export interface ModelStatsOptions extends ApiRequestOptions {
  provider?: string;
  /** Time window for aggregation (e.g. "7d", "24h", "30d"). */
  timeWindow?: string;
}

/** Fetch aggregated usage stats for a specific model. */
export function getModelStats(
  model: string,
  options?: ModelStatsOptions,
) {
  const params = new URLSearchParams();
  if (options?.provider) params.set("provider", options.provider);
  if (options?.timeWindow) params.set("window", options.timeWindow);
  const qs = params.toString();
  const path = `/api/v1/models/${encodeURIComponent(model)}/stats${qs ? `?${qs}` : ""}`;
  return apiRequest<ModelStats>(path, options);
}
