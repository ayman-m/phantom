import { apiRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { ConfigValue } from "./types";

/**
 * Fetch the full platform config by loading each section individually.
 *
 * The gateway serves config by path (GET /api/v1/config/{path}), not as a
 * single root object. This function fetches workspace, providers, and
 * advanced sections in parallel and merges them. Missing sections (404)
 * are treated as empty objects (fresh installation with no saved config).
 */
export async function getConfig(
  options?: ApiRequestOptions,
): ReturnType<typeof apiRequest<Record<string, unknown>>> {
  const sections = ["workspace", "providers", "advanced", "security"] as const;

  const results = await Promise.all(
    sections.map((section) =>
      apiRequest<Record<string, unknown>>(
        `/api/v1/config/${section}`,
        options,
      ),
    ),
  );

  const merged: Record<string, unknown> = {};

  for (let i = 0; i < sections.length; i++) {
    const result = results[i];
    if (result.ok) {
      // The API returns a ConfigSnapshot: {config_id, path, value: {...}, hash}.
      // Unwrap the `value` field so consumers get the actual config data.
      const snapshot = result.data as Record<string, unknown>;
      merged[sections[i]] =
        snapshot.value !== undefined && snapshot.value !== null
          ? snapshot.value
          : snapshot;
    } else if (result.error.code === "NOT_FOUND" || result.error.code === "HTTP_404") {
      // Section doesn't exist yet — use empty default
      merged[sections[i]] = {};
    } else {
      // Real error — propagate it
      return result;
    }
  }

  return { ok: true, data: merged };
}

/** Fetch a single config section from GET /api/v1/config/:path. */
export function getConfigPath(path: string, options?: ApiRequestOptions) {
  return apiRequest<ConfigValue>(
    `/api/v1/config/${encodeURIComponent(path)}`,
    options,
  );
}

/** Update a config section via PUT /api/v1/config/:path with optimistic hash. */
export function setConfigPath(
  path: string,
  value: unknown,
  hash: string,
  options?: ApiRequestOptions,
) {
  return apiRequest<ConfigValue>(
    `/api/v1/config/${encodeURIComponent(path)}`,
    {
      ...options,
      method: "PUT",
      body: { value, hash },
    },
  );
}
