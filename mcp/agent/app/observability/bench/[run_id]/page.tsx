"use client";

/**
 * /observability/bench/[run_id]
 *
 * Per-run detail page: shows the 5-axis aggregate scores at the top,
 * then a case-by-case table with each case's correctness / Jaccard /
 * cost / wall / error. Operators identify regressions or one-off
 * bad cases here.
 */

import { useCallback, useEffect, useState, use } from "react";
import Link from "next/link";
import { formatBenchCost, formatBenchCostPair } from "@/lib/bench-cost";

interface CaseScore {
  case_id: string;
  correctness: boolean | null;
  tool_call_jaccard: number;
  cost_usd: number | null; // null = unpriced
  wall_seconds: number;
  wall_warning: boolean;
  error: string | null;
}

interface RunDetail {
  run_id: string;
  manifest_id: string;
  started_at: string;
  completed_at: string;
  router_preset?: string | null;
  summary: {
    run_id: string;
    manifest_id: string;
    started_at: string;
    completed_at: string;
    case_count: number;
    correctness_rate: number;
    avg_tool_jaccard: number;
    cost_p50: number | null;
    cost_p95: number | null;
    wall_p50: number;
    wall_p95: number;
    infrastructure_errors: number;
    cases: CaseScore[];
  };
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function BenchRunDetailPage({
  params,
}: {
  params: Promise<{ run_id: string }>;
}) {
  const { run_id } = use(params);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/agent/bench/runs/${encodeURIComponent(run_id)}`,
        { cache: "no-store" },
      );
      if (!r.ok) {
        if (r.status === 404) {
          setError("Run not found.");
        } else {
          throw new Error(`detail ${r.status}`);
        }
        return;
      }
      const data = (await r.json()) as { run?: RunDetail };
      if (!data.run) {
        setError("Empty response.");
        return;
      }
      setRun(data.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [run_id]);

  useEffect(() => {
    void fetchDetail();
  }, [fetchDetail]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1100px] mx-auto px-8 py-8 space-y-6">
        <div>
          <Link
            href="/observability/bench"
            className="text-xs text-on-surface-variant hover:text-on-surface inline-flex items-center gap-1"
          >
            <span className="material-symbols-outlined text-sm">
              arrow_back
            </span>
            Back to runs
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading run…
          </div>
        ) : error ? (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        ) : run ? (
          <>
            <div>
              <h1 className="font-mono text-lg font-bold text-on-surface mb-1 truncate">
                {run.run_id}
              </h1>
              <div className="text-xs text-on-surface-variant flex flex-wrap items-center gap-2">
                <span className="font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary">
                  {run.manifest_id}
                </span>
                {run.router_preset && (
                  <span className="font-mono px-1.5 py-0.5 rounded bg-secondary/15 text-secondary">
                    {run.router_preset}
                  </span>
                )}
                <span>
                  {run.summary.started_at} → {run.summary.completed_at}
                </span>
              </div>
            </div>

            {/* Aggregate metrics */}
            <div
              className="rounded-2xl p-5 grid grid-cols-2 md:grid-cols-5 gap-4"
              style={glassCard}
            >
              <Metric
                label="Correctness"
                value={`${(run.summary.correctness_rate * 100).toFixed(0)}%`}
              />
              <Metric
                label="Avg Jaccard"
                value={run.summary.avg_tool_jaccard.toFixed(2)}
              />
              <Metric
                label="Cost p50 / p95"
                value={formatBenchCostPair(run.summary.cost_p50, run.summary.cost_p95)}
              />
              <Metric
                label="Wall p50 / p95"
                value={`${run.summary.wall_p50.toFixed(1)}s / ${run.summary.wall_p95.toFixed(1)}s`}
              />
              <Metric
                label="Cases (clean / total)"
                value={`${run.summary.case_count - run.summary.infrastructure_errors} / ${run.summary.case_count}`}
              />
            </div>

            {/* Per-case table */}
            <div className="rounded-2xl overflow-hidden" style={glassCard}>
              <table className="w-full text-xs">
                <thead className="bg-white/5">
                  <tr className="text-on-surface-variant/80">
                    <th className="text-left px-4 py-2 font-label">Case</th>
                    <th className="text-left px-4 py-2 font-label">Correctness</th>
                    <th className="text-left px-4 py-2 font-label">Jaccard</th>
                    <th className="text-left px-4 py-2 font-label">Cost</th>
                    <th className="text-left px-4 py-2 font-label">Wall</th>
                    <th className="text-left px-4 py-2 font-label">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {run.summary.cases.map((c) => (
                    <tr
                      key={c.case_id}
                      className="border-t border-white/5 hover:bg-white/2"
                    >
                      <td className="px-4 py-3 font-mono text-on-surface">
                        {c.case_id}
                      </td>
                      <td className="px-4 py-3">
                        {c.correctness === null ? (
                          <span className="text-on-surface-variant/50">
                            n/a
                          </span>
                        ) : c.correctness ? (
                          <span className="text-tertiary">✓ pass</span>
                        ) : (
                          <span className="text-error">✗ fail</span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-on-surface-variant">
                        {c.tool_call_jaccard.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 font-mono text-on-surface-variant">
                        {formatBenchCost(c.cost_usd)}
                      </td>
                      <td className="px-4 py-3 font-mono text-on-surface-variant">
                        {c.wall_seconds.toFixed(1)}s
                        {c.wall_warning && (
                          <span
                            className="ml-1 text-tertiary"
                            title="exceeded max_wall_seconds"
                          >
                            ⚠
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-error/80 max-w-md truncate">
                        {c.error ?? ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
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
