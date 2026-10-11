"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Metrics page — phantom version. Parses /api/v1/metrics
 * (Prometheus text format) client-side and lists every emitted
 * series with its labels and value. No PromQL, no Grafana — just a
 * searchable table over what the embedded MCP currently exposes.
 *
 * Counters/gauges show as-is. Histograms decompose into _bucket /
 * _count / _sum series; we don't fold those into a single row, so
 * histogram quantiles aren't computed here. For deeper analysis,
 * point a real Prometheus scraper at /api/v1/metrics.
 */

interface MetricRow {
  name: string;
  value: number;
  labels: Record<string, string>;
}

function parsePromText(text: string): { rows: MetricRow[]; help: Record<string, string>; type: Record<string, string> } {
  const rows: MetricRow[] = [];
  const help: Record<string, string> = {};
  const type: Record<string, string> = {};
  for (const line of text.split("\n")) {
    if (!line) continue;
    if (line.startsWith("# HELP ")) {
      const m = /^# HELP (\S+) (.*)$/.exec(line);
      if (m) help[m[1]] = m[2];
      continue;
    }
    if (line.startsWith("# TYPE ")) {
      const m = /^# TYPE (\S+) (\S+)$/.exec(line);
      if (m) type[m[1]] = m[2];
      continue;
    }
    if (line.startsWith("#")) continue;
    const m = /^([A-Za-z_][A-Za-z0-9_]*)(?:\{([^}]*)\})?\s+([0-9eE+\-.]+)/.exec(line);
    if (!m) continue;
    const labels: Record<string, string> = {};
    if (m[2]) {
      for (const pair of m[2].split(",")) {
        const eq = pair.indexOf("=");
        if (eq < 0) continue;
        const k = pair.slice(0, eq).trim();
        const v = pair.slice(eq + 1).trim().replace(/^"(.*)"$/, "$1");
        labels[k] = v;
      }
    }
    rows.push({ name: m[1], value: Number(m[3]), labels });
  }
  return { rows, help, type };
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function MetricsPage() {
  const [rows, setRows] = useState<MetricRow[]>([]);
  const [help, setHelp] = useState<Record<string, string>>({});
  const [type, setType] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/metrics", { cache: "no-store" });
      if (!r.ok) throw new Error(`metrics ${r.status}`);
      const text = await r.text();
      const parsed = parsePromText(text);
      setRows(parsed.rows);
      setHelp(parsed.help);
      setType(parsed.type);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // Group by metric family (name without _bucket / _count / _sum suffix).
  const grouped = new Map<string, MetricRow[]>();
  const f = filter.trim().toLowerCase();
  for (const r of rows) {
    if (f && !r.name.toLowerCase().includes(f)) {
      const labelText = Object.entries(r.labels).map(([k, v]) => `${k}=${v}`).join(",").toLowerCase();
      if (!labelText.includes(f)) continue;
    }
    const family = r.name.replace(/_bucket$|_count$|_sum$/, "");
    const list = grouped.get(family) ?? [];
    list.push(r);
    grouped.set(family, list);
  }

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">monitoring</span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Metrics</h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Live snapshot of every series emitted at <code className="font-mono text-xs">/api/v1/metrics</code>. Filter by name or label.
          </p>
        </div>
        <button onClick={() => void refresh()} disabled={loading}
          className="glass-panel px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50">
          <span className="material-symbols-outlined text-base align-middle mr-1">refresh</span>
          Refresh
        </button>
      </div>

      <div className="rounded-xl p-3 flex items-center gap-3" style={glassStyle}>
        <span className="material-symbols-outlined text-on-surface-variant/60">search</span>
        <input value={filter} onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by metric name or label (e.g. tool_call, scenario_started, status=success)"
          className="flex-1 bg-transparent border-0 outline-0 text-sm text-on-surface placeholder:text-on-surface-variant/40" />
        <span className="text-xs text-on-surface-variant/60 font-mono">
          {grouped.size} {grouped.size === 1 ? "family" : "families"} · {rows.length} series
        </span>
      </div>

      {error && (
        <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-16 text-sm text-on-surface-variant/60">Loading...</div>
      ) : grouped.size === 0 ? (
        <div className="text-center py-16 text-sm text-on-surface-variant/60">
          No metrics match the filter.
        </div>
      ) : (
        <div className="space-y-3">
          {[...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([family, list]) => (
            <details key={family} className="rounded-2xl overflow-hidden" style={glassStyle} open={list.length <= 6}>
              <summary className="flex items-center justify-between px-5 py-3 cursor-pointer hover:bg-white/5 transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="font-mono font-semibold text-primary truncate">{family}</span>
                  {type[family] && (
                    <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
                      {type[family]}
                    </span>
                  )}
                </div>
                <span className="text-xs text-on-surface-variant/60 font-mono">
                  {list.length} {list.length === 1 ? "series" : "series"}
                </span>
              </summary>
              {help[family] && (
                <p className="px-5 pb-2 text-xs text-on-surface-variant/70 italic">{help[family]}</p>
              )}
              <ul className="divide-y divide-outline-variant/10">
                {list.map((r, i) => (
                  <li key={i} className="grid grid-cols-12 gap-2 px-5 py-2 text-xs items-center">
                    <div className="col-span-3 font-mono text-on-surface-variant/80 truncate">{r.name}</div>
                    <div className="col-span-7 font-mono text-[11px] text-on-surface-variant/70 truncate">
                      {Object.entries(r.labels).map(([k, v]) => `${k}="${v}"`).join(", ") || "—"}
                    </div>
                    <div className="col-span-2 text-right font-mono font-semibold text-on-surface tabular-nums">
                      {r.value.toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
