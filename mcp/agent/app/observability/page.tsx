"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/**
 * Observability overview — phantom version.
 *
 * Spark's overview was Grafana-shaped: PromQL queries against a real
 * Prometheus, log-volume tiles fed by Loki, service-up rollup from a
 * scrape registry. Phantom is self-contained — no Grafana, no
 * Prometheus server, no Loki. The MCP exposes /api/v1/metrics
 * (Prometheus text) and /api/v1/audit directly; this page parses
 * them client-side.
 */

interface AuditEvent {
  id: number | string;
  ts: string;
  action: string;
  target?: string;
  status?: string;
  actor?: string;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface MetricRow {
  name: string;
  value: number;
  labels: Record<string, string>;
}

function parsePromText(text: string): MetricRow[] {
  const rows: MetricRow[] = [];
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#")) continue;
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
  return rows;
}

export default function ObservabilityOverview() {
  const [metricCount, setMetricCount] = useState<number | null>(null);
  const [topMetrics, setTopMetrics] = useState<MetricRow[]>([]);
  const [recentEvents, setRecentEvents] = useState<AuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [mResp, aResp] = await Promise.all([
          fetch("/api/agent/metrics", { cache: "no-store" }).catch(() => null),
          fetch("/api/agent/audit?limit=10", { cache: "no-store" }),
        ]);
        if (cancelled) return;

        if (mResp && mResp.ok) {
          const text = await mResp.text();
          const rows = parsePromText(text);
          setMetricCount(rows.length);
          const top = [...rows]
            .filter((r) => r.value > 0 && !r.name.endsWith("_bucket"))
            .sort((a, b) => b.value - a.value)
            .slice(0, 6);
          setTopMetrics(top);
        }

        if (aResp.ok) {
          const data = (await aResp.json()) as { events?: AuditEvent[]; count?: number };
          setRecentEvents(data.events ?? []);
          setAuditTotal(data.count ?? 0);
        } else {
          throw new Error(`audit ${aResp.status}`);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <span className="material-symbols-outlined text-2xl text-primary">monitoring</span>
          <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Observability</h1>
        </div>
        <p className="text-sm text-on-surface-variant ml-9">
          Phantom-internal observability — self-contained, no Grafana / Prometheus / Loki dependency.
          Drill in via the sidebar (Services, Metrics, Traces, Logs, Events, Pipeline).
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">{error}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Tile icon="monitoring" accent="text-primary" label="Metric series"
          value={metricCount === null ? "..." : String(metricCount)}
          hint="Prometheus-text labels emitted by the embedded MCP." />
        <Tile icon="policy" accent="text-secondary" label="Audit events"
          value={loading ? "..." : `${auditTotal}+`}
          hint="Append-only, sqlite-backed. Tail live at /activity." />
        <Tile icon="dns" accent="text-tertiary" label="Services"
          value="3" hint="phantom-agent · phantom-mcp · embedded sqlite." />
        <Tile icon="timeline" accent="text-primary-fixed-dim" label="Traces"
          value="OTel-ready" hint="Auto-instrumented OTLP. Configure an exporter to capture." />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="rounded-2xl p-6 space-y-4" style={glassStyle}>
          <div className="flex items-center justify-between">
            <h2 className="font-headline text-lg font-bold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">history_toggle_off</span>
              Recent events
            </h2>
            <Link href="/observability/events" className="text-xs text-on-surface-variant hover:text-primary transition-colors">All →</Link>
          </div>
          {loading ? <p className="text-sm text-on-surface-variant/60">Loading...</p> :
           recentEvents.length === 0 ? <p className="text-sm text-on-surface-variant/60">No audit events yet.</p> : (
            <ul className="space-y-1.5">
              {recentEvents.slice(0, 8).map((e) => (
                <li key={String(e.id)} className="flex items-baseline gap-2 text-xs">
                  <span className="font-mono text-[10px] text-on-surface-variant/50 shrink-0">{e.ts.slice(11, 19)}</span>
                  <span className="font-mono font-semibold text-primary truncate shrink-0">{e.action}</span>
                  <span className="font-mono text-on-surface-variant/70 truncate">{e.target}</span>
                  <span className="ml-auto text-[10px] text-on-surface-variant/50 shrink-0">{e.actor}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl p-6 space-y-4" style={glassStyle}>
          <div className="flex items-center justify-between">
            <h2 className="font-headline text-lg font-bold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">monitoring</span>
              Top metrics
            </h2>
            <Link href="/observability/metrics" className="text-xs text-on-surface-variant hover:text-primary transition-colors">All →</Link>
          </div>
          {loading ? <p className="text-sm text-on-surface-variant/60">Loading...</p> :
           topMetrics.length === 0 ? <p className="text-sm text-on-surface-variant/60">No metrics yet.</p> : (
            <ul className="space-y-2">
              {topMetrics.map((m, i) => (
                <li key={i} className="flex items-baseline gap-3 text-xs">
                  <span className="font-mono font-semibold text-primary truncate flex-1">{m.name}</span>
                  {Object.keys(m.labels).length > 0 && (
                    <span className="font-mono text-[10px] text-on-surface-variant/60 truncate max-w-xs">
                      {Object.entries(m.labels).map(([k, v]) => `${k}=${v}`).join(", ")}
                    </span>
                  )}
                  <span className="font-mono text-on-surface tabular-nums">{m.value.toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section>
        <h2 className="font-headline text-base font-bold text-on-surface mb-3">Drill-in</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {/* Services live under /settings (single source of truth). */}
          <SubpageCard href="/observability/metrics" icon="monitoring" label="Metrics" hint="Prometheus text" />
          <SubpageCard href="/observability/traces" icon="timeline" label="Traces" hint="OTel spans" />
          <SubpageCard href="/observability/logs" icon="terminal" label="Logs" hint="Structured events" />
          <SubpageCard href="/observability/events" icon="policy" label="Events" hint="Audit log" />
          <SubpageCard href="/observability/pipeline" icon="account_tree" label="Pipeline" hint="Component health" />
        </div>
      </section>
    </div>
  );
}

function Tile({ icon, accent, label, value, hint }: {
  icon: string; accent: string; label: string; value: string; hint: string;
}) {
  return (
    <div className="rounded-2xl p-5 space-y-2" style={glassStyle}>
      <div className="flex items-center gap-2">
        <span className={`material-symbols-outlined ${accent}`}>{icon}</span>
        <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/70">{label}</span>
      </div>
      <p className="text-2xl font-bold font-headline text-on-surface">{value}</p>
      <p className="text-[10px] text-on-surface-variant/60 leading-relaxed">{hint}</p>
    </div>
  );
}

function SubpageCard({ href, icon, label, hint }: {
  href: string; icon: string; label: string; hint: string;
}) {
  return (
    <Link href={href} className="rounded-xl p-4 space-y-1 hover:shadow-[0_0_15px_rgba(31,123,255,0.15)] transition-shadow group" style={glassStyle}>
      <span className="material-symbols-outlined text-primary group-hover:text-primary-fixed-dim transition-colors">{icon}</span>
      <p className="text-sm font-headline font-bold text-on-surface">{label}</p>
      <p className="text-[10px] text-on-surface-variant/60">{hint}</p>
    </Link>
  );
}
