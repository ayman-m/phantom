import type { ApiError } from "@/lib/api/types";
import type { ApiResult } from "@/lib/api/client";

/**
 * Typed Prometheus HTTP API client.
 *
 * Called only from server components / route handlers. The UI container
 * sits on the same Docker network as Prometheus (`spark_default`) and
 * can reach `prometheus:9090` directly without auth.
 *
 * Override the base URL with the PROMETHEUS_URL env var for non-Docker
 * dev environments (e.g. pointing at a localhost tunnel).
 */

const DEFAULT_PROMETHEUS_URL = "http://prometheus:9090";
const REQUEST_TIMEOUT_MS = 5000;

function promBaseUrl(): string {
  return process.env.PROMETHEUS_URL?.trim() || DEFAULT_PROMETHEUS_URL;
}

export type PromInstant = {
  metric: Record<string, string>;
  /** [unix_ts_seconds, value_as_string] */
  value: [number, string];
};

export type PromRange = {
  metric: Record<string, string>;
  /** Array of [unix_ts_seconds, value_as_string] samples */
  values: [number, string][];
};

export type PromTarget = {
  job: string;
  instance: string;
  health: "up" | "down" | "unknown";
  lastError: string;
  lastScrape: string;
};

type PromEnvelope<T> = {
  status: "success" | "error";
  data?: T;
  errorType?: string;
  error?: string;
};

type InstantPayload = {
  resultType: "vector";
  result: PromInstant[];
};

type RangePayload = {
  resultType: "matrix";
  result: PromRange[];
};

type TargetsPayload = {
  activeTargets: Array<{
    labels: Record<string, string>;
    discoveredLabels: Record<string, string>;
    health: string;
    lastError: string;
    lastScrape: string;
  }>;
};

async function promFetch<T>(path: string): Promise<ApiResult<T>> {
  const url = `${promBaseUrl()}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      const error: ApiError = {
        code: `PROM_${response.status}`,
        message: response.statusText || "Prometheus request failed",
        retryable: response.status >= 500,
      };
      return { ok: false, error };
    }

    const body = (await response.json()) as PromEnvelope<T>;
    if (body.status !== "success" || body.data === undefined) {
      const error: ApiError = {
        code: body.errorType ?? "PROM_ERROR",
        message: body.error ?? "Prometheus returned non-success status",
        retryable: false,
      };
      return { ok: false, error };
    }
    return { ok: true, data: body.data };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "unknown error";
    return {
      ok: false,
      error: {
        code: "PROM_NETWORK",
        message: `Prometheus fetch failed: ${msg}`,
        retryable: true,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

/** Run an instant (single-point-in-time) PromQL query. */
export async function promQueryInstant(
  query: string,
): Promise<ApiResult<PromInstant[]>> {
  const encoded = encodeURIComponent(query);
  const result = await promFetch<InstantPayload>(
    `/api/v1/query?query=${encoded}`,
  );
  if (!result.ok) return result;
  return { ok: true, data: result.data.result };
}

/**
 * Run a range query returning a time series matrix. `start`/`end` are
 * unix timestamps (seconds). `step` is a Prometheus duration string
 * like "15s" or "1m".
 */
export async function promQueryRange(
  query: string,
  opts: { start: number; end: number; step: string },
): Promise<ApiResult<PromRange[]>> {
  const params = new URLSearchParams({
    query,
    start: String(opts.start),
    end: String(opts.end),
    step: opts.step,
  });
  const result = await promFetch<RangePayload>(
    `/api/v1/query_range?${params.toString()}`,
  );
  if (!result.ok) return result;
  return { ok: true, data: result.data.result };
}

/** List scrape targets, joining job + health into a flat shape. */
export async function promTargets(): Promise<ApiResult<PromTarget[]>> {
  const result = await promFetch<TargetsPayload>("/api/v1/targets?state=any");
  if (!result.ok) return result;
  const targets: PromTarget[] = result.data.activeTargets.map((t) => ({
    job: t.labels.job ?? t.discoveredLabels.job ?? "unknown",
    instance: t.labels.instance ?? "",
    health:
      t.health === "up"
        ? "up"
        : t.health === "down"
          ? "down"
          : "unknown",
    lastError: t.lastError,
    lastScrape: t.lastScrape,
  }));
  return { ok: true, data: targets };
}

/**
 * Convenience helper for Prometheus scalar queries (e.g. sum/count)
 * where the caller just wants a single number back.
 *
 * Returns NaN if no data points matched — pages should treat NaN as
 * "no data" and render a dash.
 */
export async function promScalar(query: string): Promise<ApiResult<number>> {
  const result = await promQueryInstant(query);
  if (!result.ok) return result;
  const first = result.data[0];
  if (!first) return { ok: true, data: Number.NaN };
  return { ok: true, data: Number.parseFloat(first.value[1]) };
}
