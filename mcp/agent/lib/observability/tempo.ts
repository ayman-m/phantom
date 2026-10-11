import type { ApiError } from "@/lib/api/types";
import type { ApiResult } from "@/lib/api/client";

/**
 * Typed Tempo HTTP API client.
 *
 * Called only from server components / route handlers. The UI container
 * reaches `tempo:3200` directly on the Docker network — no auth needed.
 * Override with the TEMPO_URL env var for non-Docker dev.
 *
 * Tempo endpoints used:
 *   /api/search                        — TraceQL / tag-based search
 *   /api/traces/{traceID}              — full trace by ID
 *   /api/search/tag/service.name/values — enumerate service.name values
 *   /ready                             — health probe
 */

const DEFAULT_TEMPO_URL = "http://tempo:3200";
const REQUEST_TIMEOUT_MS = 5000;

function tempoBaseUrl(): string {
  return process.env.TEMPO_URL?.trim() || DEFAULT_TEMPO_URL;
}

export type TempoTraceSummary = {
  traceID: string;
  rootServiceName: string;
  rootTraceName: string;
  /** Duration in milliseconds. */
  durationMs: number;
  startTimeUnixNano: string;
  /** True if any span in the trace has a non-OK status. */
  hasError: boolean;
};

export type TempoSpanEvent = {
  name: string;
  timeUnixNano: number;
  attributes: Record<string, string>;
};

export type TempoSpan = {
  spanID: string;
  parentSpanID?: string;
  name: string;
  kind: string;
  serviceName: string;
  startNano: number;
  endNano: number;
  /** true if span has status=ERROR */
  hasError: boolean;
  attributes: Record<string, string | number | boolean>;
  events: TempoSpanEvent[];
};

export type TempoTrace = {
  traceID: string;
  spans: TempoSpan[];
  rootSpan: TempoSpan;
};

// Raw Tempo API shapes (documented here to keep the rest of the code typed
// and avoid littering `any`).

type RawSearchEnvelope = {
  traces?: Array<{
    traceID: string;
    rootServiceName?: string;
    rootTraceName?: string;
    durationMs?: number;
    startTimeUnixNano?: string;
    spanSets?: Array<{ matched?: number; spans?: Array<unknown> }>;
  }>;
};

type RawTagValuesEnvelope = {
  tagValues?: string[];
};

type RawAttr = {
  key: string;
  value?: {
    stringValue?: string;
    intValue?: string | number;
    doubleValue?: number;
    boolValue?: boolean;
    arrayValue?: { values: RawAttr["value"][] };
  };
};

type RawEvent = {
  timeUnixNano?: string;
  name?: string;
  attributes?: RawAttr[];
};

type RawSpan = {
  spanId?: string;
  traceId?: string;
  parentSpanId?: string;
  name?: string;
  kind?: string;
  startTimeUnixNano?: string;
  endTimeUnixNano?: string;
  status?: { code?: number | string };
  attributes?: RawAttr[];
  events?: RawEvent[];
};

type RawResourceSpans = {
  resource?: { attributes?: RawAttr[] };
  instrumentationLibrarySpans?: Array<{ spans?: RawSpan[] }>;
  scopeSpans?: Array<{ spans?: RawSpan[] }>;
};

type RawTraceEnvelope = {
  batches?: RawResourceSpans[];
  // v2 shape
  resourceSpans?: RawResourceSpans[];
};

function flattenAttr(attr: RawAttr["value"]): string | number | boolean {
  if (!attr) return "";
  if (attr.stringValue !== undefined) return attr.stringValue;
  if (attr.intValue !== undefined) return Number(attr.intValue);
  if (attr.doubleValue !== undefined) return attr.doubleValue;
  if (attr.boolValue !== undefined) return attr.boolValue;
  if (attr.arrayValue) {
    return attr.arrayValue.values.map((v) => flattenAttr(v)).join(", ");
  }
  return "";
}

function attrsToMap(
  attrs: RawAttr[] | undefined,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const a of attrs ?? []) {
    out[a.key] = flattenAttr(a.value);
  }
  return out;
}

async function tempoFetch<T>(path: string): Promise<ApiResult<T>> {
  const url = `${tempoBaseUrl()}${path}`;
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
        code: `TEMPO_${response.status}`,
        message: response.statusText || "Tempo request failed",
        retryable: response.status >= 500,
      };
      return { ok: false, error };
    }
    const body = (await response.json()) as T;
    return { ok: true, data: body };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "unknown error";
    return {
      ok: false,
      error: {
        code: "TEMPO_NETWORK",
        message: `Tempo fetch failed: ${msg}`,
        retryable: true,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Search for recent traces. With no opts, returns the most recent traces
 * across all services (limit 20). The Tempo search API requires either
 * `tags=` or `q=` in all versions; we send an empty `q={}` TraceQL
 * matcher when no filters are provided.
 *
 * Precedence (highest first):
 *   1. `traceql`  — raw TraceQL string, e.g. `{ duration > 100ms }`
 *   2. `serviceName` + optional `minDurationMs` — tag-based search
 *   3. neither   — empty TraceQL matcher returning most recent
 */
export async function tempoSearch(
  opts: {
    /** Raw TraceQL expression. Takes precedence over serviceName. */
    traceql?: string;
    serviceName?: string;
    minDurationMs?: number;
    limit?: number;
    start?: number;
    end?: number;
  } = {},
): Promise<ApiResult<TempoTraceSummary[]>> {
  // The caller's `limit` is how many rows the UI wants to render.
  // Tempo's /api/search in single-binary mode returns traces in
  // block-scan order, NOT newest-first. On a busy system with health
  // probes emitting spans every ~5s, a 15-minute search window
  // contains ~800 traces — and the first 100 of those (in scan
  // order) can easily all be from an older block, burying the
  // actual-most-recent chat/runtime traces past the end of our
  // requested limit.
  //
  // Work around it by fetching a large fixed ceiling (500 traces)
  // and sorting by startTimeUnixNano descending on the client. 500
  // is enough headroom to catch the newest traces even when the
  // window is dominated by health-probe noise, and the JSON payload
  // stays under ~40KB which is trivial on the docker network.
  const wantLimit = opts.limit ?? 20;
  const fetchLimit = Math.max(wantLimit, 500);

  const params = new URLSearchParams();
  params.set("limit", String(fetchLimit));
  if (opts.start) params.set("start", String(opts.start));
  if (opts.end) params.set("end", String(opts.end));

  const trimmedTraceql = opts.traceql?.trim();
  if (trimmedTraceql) {
    // Tempo's TraceQL endpoint requires the matcher to be wrapped in
    // braces. Be permissive: accept either `{ ... }` or bare `...` from
    // the user and normalise to the braced form before sending.
    const wrapped = trimmedTraceql.startsWith("{")
      ? trimmedTraceql
      : `{ ${trimmedTraceql} }`;
    params.set("q", wrapped);
  } else if (opts.serviceName) {
    // Tag-based search is supported by every Tempo version and is the
    // simplest way to filter by service.name.
    params.set("tags", `service.name=${opts.serviceName}`);
  } else {
    // TraceQL empty-matcher returns the most recent traces across all
    // services. Falls back to `tags=` if q is rejected.
    params.set("q", "{}");
  }
  if (opts.minDurationMs) {
    params.set("minDuration", `${opts.minDurationMs}ms`);
  }

  const result = await tempoFetch<RawSearchEnvelope>(
    `/api/search?${params.toString()}`,
  );
  if (!result.ok) {
    // Retry without TraceQL if the server rejected the q= form.
    if (!opts.serviceName && params.has("q")) {
      params.delete("q");
      const retry = await tempoFetch<RawSearchEnvelope>(
        `/api/search?${params.toString()}`,
      );
      if (!retry.ok) return retry;
      return {
        ok: true,
        data: sortAndSlice(
          (retry.data.traces ?? []).map(toSummary),
          wantLimit,
        ),
      };
    }
    return result;
  }
  return {
    ok: true,
    data: sortAndSlice(
      (result.data.traces ?? []).map(toSummary),
      wantLimit,
    ),
  };
}

/**
 * Sort trace summaries by `startTimeUnixNano` descending (newest
 * first) and slice to the caller's requested limit.
 *
 * Nanosecond timestamps are strings because they exceed JavaScript's
 * safe integer range. Use a length-first lexicographic compare which
 * is correct for non-negative same-base integer strings and faster
 * than `BigInt` parsing per comparison. This is the same trick used
 * in the Loki live-tail cursor dedup.
 */
function sortAndSlice(
  summaries: TempoTraceSummary[],
  limit: number,
): TempoTraceSummary[] {
  return [...summaries]
    .sort((a, b) => {
      const aTs = a.startTimeUnixNano;
      const bTs = b.startTimeUnixNano;
      if (aTs.length !== bTs.length) return bTs.length - aTs.length;
      if (aTs === bTs) return 0;
      return aTs < bTs ? 1 : -1;
    })
    .slice(0, limit);
}

function toSummary(
  t: NonNullable<RawSearchEnvelope["traces"]>[number],
): TempoTraceSummary {
  return {
    traceID: t.traceID,
    rootServiceName: t.rootServiceName ?? "unknown",
    rootTraceName: t.rootTraceName ?? "(unnamed)",
    durationMs: t.durationMs ?? 0,
    startTimeUnixNano: t.startTimeUnixNano ?? "0",
    hasError: false, // Tempo search doesn't surface per-trace status directly.
  };
}

/** Fetch a full trace by ID and flatten it into sorted spans. */
export async function tempoGetTrace(
  traceID: string,
): Promise<ApiResult<TempoTrace>> {
  const result = await tempoFetch<RawTraceEnvelope>(`/api/traces/${traceID}`);
  if (!result.ok) return result;

  const batches = result.data.batches ?? result.data.resourceSpans ?? [];
  const spans: TempoSpan[] = [];

  for (const rs of batches) {
    const resourceAttrs = attrsToMap(rs.resource?.attributes);
    const serviceName =
      typeof resourceAttrs["service.name"] === "string"
        ? (resourceAttrs["service.name"] as string)
        : "unknown";

    const spansList = (rs.instrumentationLibrarySpans ?? rs.scopeSpans ?? [])
      .flatMap((ss) => ss.spans ?? []);

    for (const raw of spansList) {
      const startNano = Number(raw.startTimeUnixNano ?? 0);
      const endNano = Number(raw.endTimeUnixNano ?? 0);
      const statusCode = raw.status?.code;
      const hasError =
        statusCode === 2 ||
        statusCode === "STATUS_CODE_ERROR" ||
        statusCode === "ERROR";
      spans.push({
        spanID: raw.spanId ?? "",
        parentSpanID: raw.parentSpanId || undefined,
        name: raw.name ?? "(unnamed)",
        kind: String(raw.kind ?? ""),
        serviceName,
        startNano,
        endNano,
        hasError,
        attributes: attrsToMap(raw.attributes),
        events: (raw.events ?? []).map((e) => ({
          name: e.name ?? "",
          timeUnixNano: Number(e.timeUnixNano ?? 0),
          attributes: Object.fromEntries(
            Object.entries(attrsToMap(e.attributes)).map(([k, v]) => [
              k,
              String(v),
            ]),
          ),
        })),
      });
    }
  }

  if (spans.length === 0) {
    return {
      ok: false,
      error: {
        code: "TEMPO_EMPTY_TRACE",
        message: `Trace ${traceID} returned no spans`,
        retryable: false,
      },
    };
  }

  // Sort by startNano so the waterfall rendering is deterministic.
  spans.sort((a, b) => a.startNano - b.startNano);

  // Identify the root: a span without a parentSpanID, or with a parent
  // that is not in this trace. Fall back to the earliest span.
  const spanIds = new Set(spans.map((s) => s.spanID));
  const rootCandidates = spans.filter(
    (s) => !s.parentSpanID || !spanIds.has(s.parentSpanID),
  );
  const rootSpan = rootCandidates[0] ?? spans[0];

  return { ok: true, data: { traceID, spans, rootSpan } };
}

/** Enumerate `service.name` values that Tempo has seen recently. */
export async function tempoServiceNames(): Promise<ApiResult<string[]>> {
  const result = await tempoFetch<RawTagValuesEnvelope>(
    "/api/search/tag/service.name/values",
  );
  if (!result.ok) return result;
  return { ok: true, data: result.data.tagValues ?? [] };
}

/** Ready probe used by the shell header. */
export async function tempoReady(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`${tempoBaseUrl()}/ready`, {
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
