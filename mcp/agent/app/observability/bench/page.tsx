"use client";

/**
 * /observability/bench
 *
 * Surfaces the BenchRunStore (storage + runner) as
 * an operator-browsable list of past bench runs + a per-run drill-
 * down. The "Run benchmark" button lets operators trigger a new run
 * from the UI without going through chat.
 *
 * Columns:
 *   - Run id (truncated; clickable for detail)
 *   - Manifest id
 *   - Started at (relative)
 *   - Router preset (the model override that was passed, or
 *     "(router default)" when unset)
 *   - Quick metrics from the stored summary (correctness rate, avg
 *     Jaccard, cost p50, wall p50)
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

interface RunRow {
  run_id: string;
  manifest_id: string;
  started_at: string;
  completed_at: string;
  router_preset?: string | null;
}

interface RunSummary extends RunRow {
  summary?: {
    correctness_rate: number;
    avg_tool_jaccard: number;
    cost_p50: number;
    wall_p50: number;
    case_count: number;
    infrastructure_errors: number;
  };
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function BenchPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [manifest, setManifest] = useState("phantom-soc-v1");
  const [routerPreset, setRouterPreset] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/bench/runs?limit=50", {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`runs fetch ${r.status}`);
      const data = (await r.json()) as { runs?: RunRow[] };
      // Fetch each run's full summary in parallel for the row metrics.
      // Capped at 50 runs so this is bounded.
      const enriched = await Promise.all(
        (data.runs ?? []).map(async (row): Promise<RunSummary> => {
          try {
            const dr = await fetch(
              `/api/agent/bench/runs/${encodeURIComponent(row.run_id)}`,
              { cache: "no-store" },
            );
            if (!dr.ok) return row;
            const detail = (await dr.json()) as {
              run?: { summary?: RunSummary["summary"] };
            };
            return { ...row, summary: detail.run?.summary };
          } catch {
            return row;
          }
        }),
      );
      setRuns(enriched);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/bench/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          manifest,
          router_preset_model: routerPreset.trim() || undefined,
        }),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`run ${r.status}: ${text.slice(0, 200)}`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [manifest, routerPreset, refresh]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1200px] mx-auto px-8 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                speed
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Benchmark runs
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9 max-w-2xl">
              Browse past benchmark runs from <code className="font-mono text-xs">benchmark_runs.db</code> +
              fire new runs from this page. Each run scores a manifest&apos;s
              cases on 5 axes (correctness, tool-call Jaccard, cost
              p50/p95, wall p50/p95, infrastructure errors).
            </p>
          </div>
          <Link
            href="/observability/bench/compare"
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface bg-white/5 hover:bg-white/10 transition-colors inline-flex items-center gap-1.5"
          >
            <span className="material-symbols-outlined text-base">
              compare_arrows
            </span>
            Compare runs
          </Link>
        </div>

        {/* Run-now form */}
        <div className="rounded-2xl p-5 space-y-3" style={glassCard}>
          <h2 className="text-sm font-semibold text-on-surface">Run a benchmark</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-label text-on-surface-variant/80">
                Manifest (path or bundled id)
              </label>
              <input
                type="text"
                value={manifest}
                onChange={(e) => setManifest(e.target.value)}
                placeholder="phantom-soc-v1"
                className="w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-label text-on-surface-variant/80">
                Router preset model (optional)
              </label>
              <input
                type="text"
                value={routerPreset}
                onChange={(e) => setRouterPreset(e.target.value)}
                placeholder="(runtime default)"
                className="w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
              />
            </div>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => void handleRun()}
                disabled={running || !manifest.trim()}
                className="px-4 py-2 rounded-xl text-xs font-medium text-on-primary-container bg-primary-container/30 hover:bg-primary-container/50 transition-colors disabled:opacity-50"
              >
                {running ? "Running…" : "Run benchmark"}
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading runs…
          </div>
        ) : runs.length === 0 ? (
          <div className="text-center py-12 rounded-2xl" style={glassCard}>
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              speed
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              No benchmark runs yet.
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto leading-relaxed">
              Fire one from the form above with manifest{" "}
              <span className="font-mono">phantom-soc-v1</span> (the bundled
              3-case sample corpus).
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {runs.map((row) => (
              <Link
                key={row.run_id}
                href={`/observability/bench/${encodeURIComponent(row.run_id)}`}
                className="rounded-2xl p-4 hover:bg-white/2 transition-colors block"
                style={glassCard}
              >
                <div className="flex items-baseline justify-between gap-3 flex-wrap mb-1">
                  <div className="font-mono text-sm font-semibold text-on-surface truncate">
                    {row.run_id}
                  </div>
                  <div className="text-[11px] font-mono text-on-surface-variant/60">
                    {row.started_at}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary">
                    {row.manifest_id}
                  </span>
                  {row.router_preset && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary/15 text-secondary">
                      {row.router_preset}
                    </span>
                  )}
                </div>
                {row.summary && (
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
                    <Metric
                      label="Correctness"
                      value={`${(row.summary.correctness_rate * 100).toFixed(0)}%`}
                    />
                    <Metric
                      label="Avg Jaccard"
                      value={row.summary.avg_tool_jaccard.toFixed(2)}
                    />
                    <Metric
                      label="Cost p50"
                      value={`$${row.summary.cost_p50.toFixed(4)}`}
                    />
                    <Metric
                      label="Wall p50"
                      value={`${row.summary.wall_p50.toFixed(1)}s`}
                    />
                    <Metric
                      label="Cases"
                      value={`${row.summary.case_count - row.summary.infrastructure_errors}/${row.summary.case_count}`}
                    />
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-label text-on-surface-variant/60 uppercase">
        {label}
      </div>
      <div className="font-mono text-sm text-on-surface">{value}</div>
    </div>
  );
}
