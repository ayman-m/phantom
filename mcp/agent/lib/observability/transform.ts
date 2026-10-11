import type { PromInstant, PromRange } from "./prometheus";
import type { TempoTrace, TempoSpan } from "./tempo";

/**
 * Pure transformers that turn raw PromQL / Loki / Tempo responses into
 * the shapes the Observability pages need. Keeping these in one place
 * lets the page files stay thin (fetch -> transform -> render) and
 * makes them trivially unit-testable.
 */

// --- Service health ---------------------------------------------------------

export type ServiceStatusKind = "healthy" | "degraded" | "down";

export type ServiceHealth = {
  name: string;
  status: ServiceStatusKind;
  /** p95 latency in ms. 0 if no data. */
  p95Ms: number;
  /** Relative request rate 0..1, used to draw the mini bar. */
  loadRatio: number;
  /** Optional note explaining non-healthy status. */
  note?: string;
};

export const DEGRADED_LATENCY_MS = 500;

/**
 * Merge the three PromQL result sets:
 *   - `up`: up{job=~".*"} -- scrape target health
 *   - `p95`: histogram_quantile p95 by job -- per-service latency
 *   - `rate`: sum by (job) (rate(...)) -- per-service request rate
 */
export function buildServiceHealth(
  up: PromInstant[],
  p95: PromInstant[],
  rate: PromInstant[],
  options: { degradedLatencyMs?: number } = {},
): ServiceHealth[] {
  const degraded = options.degradedLatencyMs ?? DEGRADED_LATENCY_MS;

  const p95ByJob = new Map<string, number>();
  for (const row of p95) {
    const job = row.metric.job ?? row.metric.service_name ?? "";
    if (!job) continue;
    const val = Number.parseFloat(row.value[1]);
    if (Number.isFinite(val)) p95ByJob.set(job, val);
  }

  const rateByJob = new Map<string, number>();
  for (const row of rate) {
    const job = row.metric.job ?? row.metric.service_name ?? "";
    if (!job) continue;
    const val = Number.parseFloat(row.value[1]);
    if (Number.isFinite(val)) rateByJob.set(job, val);
  }

  const maxRate = Math.max(1e-9, ...rateByJob.values());

  const services: ServiceHealth[] = [];
  for (const row of up) {
    const job = row.metric.job ?? "";
    if (!job) continue;
    const upVal = Number.parseFloat(row.value[1]);
    const isUp = upVal === 1;
    const p95Ms = p95ByJob.get(job) ?? 0;
    const rateVal = rateByJob.get(job) ?? 0;

    let status: ServiceStatusKind = "healthy";
    let note: string | undefined;
    if (!isUp) {
      status = "down";
      note = row.metric.instance
        ? `scrape target ${row.metric.instance} unreachable`
        : "scrape target unreachable";
    } else if (p95Ms > degraded) {
      status = "degraded";
      note = `p95 ${Math.round(p95Ms)}ms over ${degraded}ms threshold`;
    }

    services.push({
      name: job,
      status,
      p95Ms,
      loadRatio: rateVal / maxRate,
      note,
    });
  }

  const statusOrder: Record<ServiceStatusKind, number> = {
    healthy: 0,
    degraded: 1,
    down: 2,
  };
  services.sort((a, b) => {
    const so = statusOrder[a.status] - statusOrder[b.status];
    return so !== 0 ? so : a.name.localeCompare(b.name);
  });

  return services;
}

// --- Log line parsing -------------------------------------------------------

export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR";

export type ParsedLogLine = {
  timestamp: string;
  service: string;
  level: LogLevel;
  message: string;
  traceId?: string;
  rawJson?: Record<string, unknown>;
};

const LEVEL_REGEX =
  /\b(DEBUG|INFO|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL)\b/i;

// Matches an nginx-style access log: `IP - - [date] "METHOD path HTTP/x.y" STATUS bytes ...`
// We anchor on the literal `HTTP/` followed by a status code so URLs containing
// "HTTP" or "ERROR" don't match — only the actual response status does.
const NGINX_STATUS_REGEX =
  /"\s*[A-Z]+\s+[^"]*\s+HTTP\/\d+\.\d+"\s+(\d{3})\b/;

function normaliseLevel(raw: string | undefined): LogLevel {
  if (!raw) return "INFO";
  const upper = raw.toUpperCase();
  if (upper.startsWith("DEB")) return "DEBUG";
  if (upper.startsWith("WARN")) return "WARN";
  if (upper.startsWith("ERR") || upper === "FATAL" || upper === "CRITICAL")
    return "ERROR";
  return "INFO";
}

/** Convert an HTTP status code to a log level. 5xx → ERROR, 4xx → WARN, else INFO. */
function levelFromHttpStatus(status: number): LogLevel {
  if (status >= 500) return "ERROR";
  if (status >= 400) return "WARN";
  return "INFO";
}

/**
 * Best-effort log line parser. Tries JSON first (structured logs from
 * slogutil), then falls back to regex-based level extraction. `container`
 * is the Loki stream label and is used as the default service.
 */
export function parseLogLine(
  nanoTimestamp: string,
  line: string,
  container: string,
): ParsedLogLine {
  const tsSec = Number(nanoTimestamp) / 1_000_000_000;
  const timestamp = Number.isFinite(tsSec)
    ? new Date(tsSec * 1000).toISOString().replace("T", " ").slice(0, 23)
    : nanoTimestamp;

  const service = container.replace(/^spark-/, "").replace(/-1$/, "");

  try {
    const json = JSON.parse(line) as Record<string, unknown>;
    const level = normaliseLevel(
      typeof json.level === "string"
        ? (json.level as string)
        : typeof json.severity === "string"
          ? (json.severity as string)
          : undefined,
    );
    const msg =
      typeof json.msg === "string"
        ? (json.msg as string)
        : typeof json.message === "string"
          ? (json.message as string)
          : line;
    const traceId =
      typeof json.trace_id === "string"
        ? (json.trace_id as string)
        : typeof json.traceId === "string"
          ? (json.traceId as string)
          : undefined;
    return {
      timestamp,
      service:
        typeof json["service.name"] === "string"
          ? (json["service.name"] as string)
          : typeof json.service === "string"
            ? (json.service as string)
            : service,
      level,
      message: msg,
      traceId,
      rawJson: json,
    };
  } catch {
    // Fall through to non-JSON parsing below.
  }

  // 1. nginx access log fast path: derive level from the HTTP status, NOT
  //    from substring matching against the URL. A line like
  //    `... "GET /api/observability/logs/recent?levels=ERROR ..." 200 496`
  //    is a SUCCESS (200) and must not be tagged as ERROR just because the
  //    URL parameter happens to contain that word.
  const nginxMatch = NGINX_STATUS_REGEX.exec(line);
  if (nginxMatch) {
    const status = Number.parseInt(nginxMatch[1]!, 10);
    return {
      timestamp,
      service,
      level: levelFromHttpStatus(status),
      message: line,
    };
  }

  // 2. Fallback for plain-text logs from Go services that emit unstructured
  //    output (rare, but exists). Scan only the FIRST 80 characters of the
  //    line so a long message body containing query params or quoted code
  //    doesn't poison the level. Most loggers put the level at the very
  //    start of the line.
  const head = line.slice(0, 80);
  const match = LEVEL_REGEX.exec(head);
  return {
    timestamp,
    service,
    level: normaliseLevel(match?.[1]),
    message: line,
  };
}

// --- Waterfall span layout --------------------------------------------------

export type WaterfallRow = {
  spanID: string;
  depth: number;
  service: string;
  name: string;
  durationMs: number;
  offsetPct: number;
  widthPct: number;
  hasError: boolean;
  events: Array<{ name: string; offsetWithinPct: number }>;
};

/**
 * Walk a TempoTrace and compute Gantt-style percentages for each span.
 * Depth is computed by following parentSpanID back to the root.
 */
export function computeWaterfallRows(trace: TempoTrace): WaterfallRow[] {
  const byId = new Map<string, TempoSpan>();
  for (const s of trace.spans) byId.set(s.spanID, s);

  function depthOf(span: TempoSpan): number {
    let d = 0;
    let cur: TempoSpan | undefined = span;
    const seen = new Set<string>();
    while (cur?.parentSpanID && byId.has(cur.parentSpanID)) {
      if (seen.has(cur.spanID)) break;
      seen.add(cur.spanID);
      cur = byId.get(cur.parentSpanID);
      d++;
      if (d > 50) break;
    }
    return d;
  }

  const rootStart = trace.rootSpan.startNano;
  const rootEnd = trace.rootSpan.endNano;
  const totalNano = Math.max(1, rootEnd - rootStart);

  return trace.spans.map((s) => {
    const offsetNano = Math.max(0, s.startNano - rootStart);
    const widthNano = Math.max(0, s.endNano - s.startNano);
    const offsetPct = (offsetNano / totalNano) * 100;
    const widthPct = Math.min(
      100 - offsetPct,
      (widthNano / totalNano) * 100,
    );
    return {
      spanID: s.spanID,
      depth: depthOf(s),
      service: s.serviceName,
      name: s.name,
      durationMs: widthNano / 1_000_000,
      offsetPct,
      widthPct,
      hasError: s.hasError,
      events: s.events.map((e) => ({
        name: e.name,
        offsetWithinPct:
          widthNano > 0
            ? ((e.timeUnixNano - s.startNano) / widthNano) * 100
            : 0,
      })),
    };
  });
}

// --- Metrics chart helpers --------------------------------------------------

export type ChartSeries = {
  label: string;
  color: string;
  values: Array<{ t: number; v: number }>;
  current: number;
  min: number;
  max: number;
  avg: number;
};

const SERIES_COLORS = [
  "#4ea2ff",
  "#a855f7",
  "#F2B8B5",
  "#7bdc7b",
  "#fbbc30",
  "#38bdf8",
  "#f472b6",
];

/**
 * Turn a PromRange matrix into labelled series with aggregate stats.
 */
export function buildChartSeries(rows: PromRange[]): ChartSeries[] {
  return rows.map((row, idx) => {
    const label =
      row.metric.service_name ??
      row.metric.job ??
      row.metric.instance ??
      `series ${idx + 1}`;
    const values = row.values
      .map(([t, v]) => ({ t, v: Number.parseFloat(v) }))
      .filter((p) => Number.isFinite(p.v));
    const nums = values.map((p) => p.v);
    const current = nums[nums.length - 1] ?? 0;
    const min = nums.length > 0 ? Math.min(...nums) : 0;
    const max = nums.length > 0 ? Math.max(...nums) : 0;
    const avg =
      nums.length > 0 ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
    return {
      label,
      color: SERIES_COLORS[idx % SERIES_COLORS.length]!,
      values,
      current,
      min,
      max,
      avg,
    };
  });
}

/**
 * Turn a ChartSeries into an SVG path string with x normalised to
 * [0, viewBoxWidth] and y normalised to [0, viewBoxHeight]. y is
 * flipped so higher values appear higher on screen.
 */
export function buildSvgPath(
  series: ChartSeries,
  viewBoxWidth: number,
  viewBoxHeight: number,
  yMin: number,
  yMax: number,
): string {
  if (series.values.length === 0) return "";
  const xMin = series.values[0]!.t;
  const xMax = series.values[series.values.length - 1]!.t;
  const xRange = Math.max(1, xMax - xMin);
  const yRange = Math.max(1e-9, yMax - yMin);

  return series.values
    .map((p, idx) => {
      const x = ((p.t - xMin) / xRange) * viewBoxWidth;
      const yNorm = (p.v - yMin) / yRange;
      const y =
        viewBoxHeight - Math.max(0, Math.min(1, yNorm)) * viewBoxHeight;
      return `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** Count datapoints where the value exceeds 2x the trailing mean of 10. */
export function countAnomalies(series: ChartSeries[]): number {
  let count = 0;
  for (const s of series) {
    const nums = s.values.map((p) => p.v);
    for (let i = 10; i < nums.length; i++) {
      const window = nums.slice(i - 10, i);
      const mean = window.reduce((a, b) => a + b, 0) / window.length;
      if (nums[i]! > mean * 2 && mean > 0) count++;
    }
  }
  return count;
}

// --- Misc formatters --------------------------------------------------------

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[u]}`;
}

export function formatRate(samplesPerSec: number, unit = "req/s"): string {
  if (!Number.isFinite(samplesPerSec) || samplesPerSec < 0) return "—";
  if (samplesPerSec >= 1000) {
    return `${(samplesPerSec / 1000).toFixed(1)}k ${unit}`;
  }
  return `${samplesPerSec.toFixed(samplesPerSec < 10 ? 1 : 0)} ${unit}`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

export function formatAgo(
  unixSeconds: number,
  now: number = Date.now() / 1000,
): string {
  const diff = now - unixSeconds;
  if (!Number.isFinite(diff) || diff < 0) return "—";
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// --- PromQL pretty printer -------------------------------------------------

/**
 * Tiny PromQL formatter — collapses runs of whitespace, then puts each
 * top-level argument of a function call on its own line with one level
 * of indent. Handles nested parens but does NOT understand operators
 * inside braces (good enough for the typical histogram_quantile / sum /
 * rate three-deep nesting). Designed to be cheap and predictable rather
 * than fully spec-compliant.
 *
 * Example input:
 *   histogram_quantile(0.95, sum by (le, job) (rate(rpc_server_call_duration_seconds_bucket[5m]))) * 1000
 *
 * Output:
 *   histogram_quantile(
 *     0.95,
 *     sum by (le, job) (
 *       rate(rpc_server_call_duration_seconds_bucket[5m])
 *     )
 *   ) * 1000
 */
export function formatPromQL(query: string): string {
  const collapsed = query.replace(/\s+/g, " ").trim();
  if (!collapsed) return "";

  let depth = 0;
  let out = "";
  let inBrackets = false; // track []  to avoid splitting [5m]
  let inBraces = false; // track {}  to avoid splitting label sets

  for (let i = 0; i < collapsed.length; i++) {
    const ch = collapsed[i]!;
    if (ch === "[") inBrackets = true;
    if (ch === "]") inBrackets = false;
    if (ch === "{") inBraces = true;
    if (ch === "}") inBraces = false;

    if (!inBrackets && !inBraces) {
      if (ch === "(") {
        depth++;
        out += "(\n" + indent(depth);
        // skip following space after (
        if (collapsed[i + 1] === " ") i++;
        continue;
      }
      if (ch === ")") {
        depth = Math.max(0, depth - 1);
        out += "\n" + indent(depth) + ")";
        continue;
      }
      if (ch === "," && depth > 0) {
        out += ",\n" + indent(depth);
        if (collapsed[i + 1] === " ") i++;
        continue;
      }
    }
    out += ch;
  }
  return out;
}

function indent(depth: number): string {
  return "  ".repeat(Math.max(0, depth));
}
