import type { ApiError } from "@/lib/api/types";
import type { ApiResult } from "@/lib/api/client";

/**
 * Typed Loki HTTP API client.
 *
 * Called only from server components / route handlers. The UI container
 * reaches `loki:3100` directly on the Docker network — no auth needed.
 * Override with the LOKI_URL env var for non-Docker dev.
 *
 * Loki endpoints used:
 *   /loki/api/v1/query_range      — logs over a time range
 *   /loki/api/v1/query            — instant metric/log queries
 *   /loki/api/v1/label/{name}/values — label value enumeration
 */

const DEFAULT_LOKI_URL = "http://loki:3100";
const REQUEST_TIMEOUT_MS = 5000;

function lokiBaseUrl(): string {
  return process.env.LOKI_URL?.trim() || DEFAULT_LOKI_URL;
}

export type LokiStream = {
  stream: Record<string, string>;
  /**
   * Each entry is [unix_ts_nanoseconds_as_string, log_line_as_string].
   * Loki returns nanoseconds as a string to preserve precision.
   */
  values: [string, string][];
};

export type LokiMatrix = {
  metric: Record<string, string>;
  values: [number, string][];
};

type LokiEnvelope<T> = {
  status: "success" | "error";
  data?: {
    resultType: string;
    result: T;
    stats?: Record<string, unknown>;
  };
  errorType?: string;
  error?: string;
};

type LokiLabelValues = {
  status: "success";
  data: string[];
};

async function lokiFetch<T>(path: string): Promise<ApiResult<T>> {
  const url = `${lokiBaseUrl()}${path}`;
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
        code: `LOKI_${response.status}`,
        message: response.statusText || "Loki request failed",
        retryable: response.status >= 500,
      };
      return { ok: false, error };
    }

    const body = (await response.json()) as {
      status?: string;
      data?: T;
      errorType?: string;
      error?: string;
    };
    if (body.status !== "success" || body.data === undefined) {
      const error: ApiError = {
        code: body.errorType ?? "LOKI_ERROR",
        message: body.error ?? "Loki returned non-success status",
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
        code: "LOKI_NETWORK",
        message: `Loki fetch failed: ${msg}`,
        retryable: true,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Run a LogQL range query and return the matching log streams.
 * `start`/`end` are unix timestamps in seconds (the wrapper converts to
 * nanoseconds as Loki expects).
 */
export async function lokiQueryRange(
  query: string,
  opts: {
    start: number;
    end: number;
    limit?: number;
    direction?: "backward" | "forward";
  },
): Promise<ApiResult<LokiStream[]>> {
  const params = new URLSearchParams({
    query,
    start: String(opts.start * 1_000_000_000),
    end: String(opts.end * 1_000_000_000),
    limit: String(opts.limit ?? 100),
    direction: opts.direction ?? "backward",
  });
  const result = await lokiFetch<{
    resultType: "streams" | "matrix";
    result: LokiStream[] | LokiMatrix[];
  }>(`/loki/api/v1/query_range?${params.toString()}`);
  if (!result.ok) return result;
  // If the caller ran a metric query accidentally (matrix result), return
  // empty streams — callers should use lokiMetricRange for those.
  if (result.data.resultType !== "streams") {
    return { ok: true, data: [] };
  }
  return { ok: true, data: result.data.result as LokiStream[] };
}

/**
 * Run a LogQL metric range query (rate, count_over_time, sum, etc).
 * Returns matrix of series with numeric samples.
 */
export async function lokiMetricRange(
  query: string,
  opts: { start: number; end: number; step: string },
): Promise<ApiResult<LokiMatrix[]>> {
  const params = new URLSearchParams({
    query,
    start: String(opts.start * 1_000_000_000),
    end: String(opts.end * 1_000_000_000),
    step: opts.step,
  });
  const result = await lokiFetch<{
    resultType: "matrix" | "streams";
    result: LokiMatrix[] | LokiStream[];
  }>(`/loki/api/v1/query_range?${params.toString()}`);
  if (!result.ok) return result;
  if (result.data.resultType !== "matrix") {
    return { ok: true, data: [] };
  }
  return { ok: true, data: result.data.result as LokiMatrix[] };
}

/**
 * Run an instant LogQL metric query and return a single scalar. Useful
 * for "current log ingest rate" style queries where the page only needs
 * one number. Returns NaN if the result was empty.
 */
export async function lokiInstantScalar(
  query: string,
): Promise<ApiResult<number>> {
  const params = new URLSearchParams({ query });
  const result = await lokiFetch<{
    resultType: string;
    result: Array<{ metric: Record<string, string>; value: [number, string] }>;
  }>(`/loki/api/v1/query?${params.toString()}`);
  if (!result.ok) return result;
  const first = result.data.result[0];
  if (!first) return { ok: true, data: Number.NaN };
  return { ok: true, data: Number.parseFloat(first.value[1]) };
}

/** Enumerate the values for a given label (e.g. "container"). */
export async function lokiLabelValues(
  label: string,
  opts?: { start?: number; end?: number },
): Promise<ApiResult<string[]>> {
  const params = new URLSearchParams();
  if (opts?.start) params.set("start", String(opts.start * 1_000_000_000));
  if (opts?.end) params.set("end", String(opts.end * 1_000_000_000));
  const qs = params.toString();
  const url = `${lokiBaseUrl()}/loki/api/v1/label/${encodeURIComponent(label)}/values${
    qs ? `?${qs}` : ""
  }`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: `LOKI_${response.status}`,
          message: response.statusText || "Loki label request failed",
          retryable: response.status >= 500,
        },
      };
    }
    const body = (await response.json()) as LokiLabelValues;
    return { ok: true, data: body.data ?? [] };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "unknown error";
    return {
      ok: false,
      error: {
        code: "LOKI_NETWORK",
        message: `Loki label fetch failed: ${msg}`,
        retryable: true,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

/** Ready probe used by the shell header. Returns true if Loki is serving. */
export async function lokiReady(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`${lokiBaseUrl()}/ready`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
