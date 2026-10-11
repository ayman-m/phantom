"use client";

/**
 * /observability/bench/compare
 *
 * Side-by-side comparison of two bench runs. Operators pick a base
 * + head run id (via URL query params or the dropdowns at the top
 * of the page) and see metric deltas with regression coloring:
 *
 *   - green = head improved over base (≥10% better)
 *   - red   = head regressed against base (≥10% worse)
 *   - neutral = within 10% (no signal)
 *
 * 10% threshold matches the bench store's regression-flag
 * definition. Per-case rows show pass/fail flip + Jaccard delta +
 * cost / wall delta so operators identify which case is the
 * regression vector when an aggregate shifts.
 *
 * Usage:
 *   /observability/bench/compare?base=<run-id>&head=<run-id>
 *
 * From the bench list page, the operator picks two runs to compare
 * and arrives here with the URL pre-populated. Without query params
 * the page renders empty selectors so the operator picks manually.
 */

import { useCallback, useEffect, useMemo, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface CaseScore {
  case_id: string;
  correctness: boolean | null;
  tool_call_jaccard: number;
  cost_usd: number;
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
    case_count: number;
    correctness_rate: number;
    avg_tool_jaccard: number;
    cost_p50: number;
    cost_p95: number;
    wall_p50: number;
    wall_p95: number;
    infrastructure_errors: number;
    cases: CaseScore[];
  };
}

interface RunListItem {
  run_id: string;
  manifest_id: string;
  started_at: string;
  router_preset?: string | null;
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const REGRESSION_THRESHOLD = 0.10; // 10% delta threshold

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-sm text-on-surface-variant/60">
          Loading…
        </div>
      }
    >
      <CompareInner />
    </Suspense>
  );
}

function CompareInner() {
  const router = useRouter();
  const params = useSearchParams();
  const initialBase = params.get("base") ?? "";
  const initialHead = params.get("head") ?? "";

  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [baseId, setBaseId] = useState(initialBase);
  const [headId, setHeadId] = useState(initialHead);
  const [base, setBase] = useState<RunDetail | null>(null);
  const [head, setHead] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the run list for the selectors.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await fetch("/api/agent/bench/runs?limit=100", {
          cache: "no-store",
        });
        if (!r.ok) throw new Error(`runs ${r.status}`);
        const data = (await r.json()) as { runs?: RunListItem[] };
        if (!cancelled) setRuns(data.runs ?? []);
      } catch (err) {
        if (!cancelled) console.warn("compare: failed to load runs:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Load the chosen detail pair.
  useEffect(() => {
    if (!baseId || !headId) {
      setBase(null);
      setHead(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [br, hr] = await Promise.all([
          fetch(`/api/agent/bench/runs/${encodeURIComponent(baseId)}`, {
            cache: "no-store",
          }),
          fetch(`/api/agent/bench/runs/${encodeURIComponent(headId)}`, {
            cache: "no-store",
          }),
        ]);
        if (!br.ok || !hr.ok) {
          throw new Error(`fetch failed (${br.status} / ${hr.status})`);
        }
        const bd = (await br.json()) as { run?: RunDetail };
        const hd = (await hr.json()) as { run?: RunDetail };
        if (cancelled) return;
        if (!bd.run || !hd.run) {
          setError("One of the runs returned empty.");
          return;
        }
        setBase(bd.run);
        setHead(hd.run);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [baseId, headId]);

  const updateBase = useCallback(
    (v: string) => {
      setBaseId(v);
      const newParams = new URLSearchParams(params.toString());
      newParams.set("base", v);
      if (headId) newParams.set("head", headId);
      router.replace(`/observability/bench/compare?${newParams.toString()}`);
    },
    [params, headId, router],
  );

  const updateHead = useCallback(
    (v: string) => {
      setHeadId(v);
      const newParams = new URLSearchParams(params.toString());
      if (baseId) newParams.set("base", baseId);
      newParams.set("head", v);
      router.replace(`/observability/bench/compare?${newParams.toString()}`);
    },
    [params, baseId, router],
  );

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1200px] mx-auto px-8 py-8 space-y-6">
        <div>
          <Link
            href="/observability/bench"
            className="text-xs text-on-surface-variant hover:text-on-surface inline-flex items-center gap-1"
          >
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to runs
          </Link>
        </div>

        <div>
          <h1 className="font-headline text-2xl font-bold text-on-surface mb-1">
            Compare bench runs
          </h1>
          <p className="text-xs text-on-surface-variant max-w-2xl">
            Side-by-side metric deltas with regression coloring. Threshold:
            ≥{Math.round(REGRESSION_THRESHOLD * 100)}% delta = green / red;
            within threshold = neutral.
          </p>
        </div>

        {/* Selectors */}
        <div className="rounded-2xl p-5 grid grid-cols-1 md:grid-cols-2 gap-4" style={glassCard}>
          <div>
            <label className="text-xs font-label text-on-surface-variant/80 uppercase tracking-widest">
              Base
            </label>
            <select
              value={baseId}
              onChange={(e) => updateBase(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
            >
              <option value="">(pick a base run)</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {r.manifest_id} · {r.router_preset ?? "default"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-label text-on-surface-variant/80 uppercase tracking-widest">
              Head
            </label>
            <select
              value={headId}
              onChange={(e) => updateHead(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-xl text-sm bg-surface-container-low border border-white/10 text-on-surface font-mono"
            >
              <option value="">(pick a head run)</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {r.manifest_id} · {r.router_preset ?? "default"}
                </option>
              ))}
            </select>
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
        ) : base && head ? (
          <>
            {/* Aggregate deltas */}
            <div className="rounded-2xl p-5 space-y-4" style={glassCard}>
              <h2 className="text-sm font-semibold text-on-surface">
                Aggregate metric deltas
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <DeltaCard
                  label="Correctness rate"
                  baseVal={base.summary.correctness_rate}
                  headVal={head.summary.correctness_rate}
                  format={(v) => `${(v * 100).toFixed(1)}%`}
                  higherIsBetter
                />
                <DeltaCard
                  label="Avg Jaccard"
                  baseVal={base.summary.avg_tool_jaccard}
                  headVal={head.summary.avg_tool_jaccard}
                  format={(v) => v.toFixed(2)}
                  higherIsBetter
                />
                <DeltaCard
                  label="Cost p50"
                  baseVal={base.summary.cost_p50}
                  headVal={head.summary.cost_p50}
                  format={(v) => `$${v.toFixed(4)}`}
                  higherIsBetter={false}
                />
                <DeltaCard
                  label="Cost p95"
                  baseVal={base.summary.cost_p95}
                  headVal={head.summary.cost_p95}
                  format={(v) => `$${v.toFixed(4)}`}
                  higherIsBetter={false}
                />
                <DeltaCard
                  label="Wall p50"
                  baseVal={base.summary.wall_p50}
                  headVal={head.summary.wall_p50}
                  format={(v) => `${v.toFixed(1)}s`}
                  higherIsBetter={false}
                />
                <DeltaCard
                  label="Wall p95"
                  baseVal={base.summary.wall_p95}
                  headVal={head.summary.wall_p95}
                  format={(v) => `${v.toFixed(1)}s`}
                  higherIsBetter={false}
                />
              </div>
            </div>

            {/* Per-case diff */}
            <PerCaseDiff base={base} head={head} />
          </>
        ) : (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              compare_arrows
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              Pick a base and head run to compare.
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto leading-relaxed">
              Useful pairings: Flash vs Pro at the same manifest; same manifest
              across two release tags; before/after a corpus change.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function DeltaCard({
  label,
  baseVal,
  headVal,
  format,
  higherIsBetter,
}: {
  label: string;
  baseVal: number;
  headVal: number;
  format: (n: number) => string;
  higherIsBetter: boolean;
}) {
  const delta = headVal - baseVal;
  const pct = baseVal !== 0 ? delta / Math.abs(baseVal) : 0;
  const significant = Math.abs(pct) >= REGRESSION_THRESHOLD;
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  const colorClass = !significant
    ? "text-on-surface-variant"
    : improved
      ? "text-tertiary"
      : "text-error";
  const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "•";
  return (
    <div className="rounded-xl bg-surface-container-low/40 p-3 space-y-1">
      <div className="text-[10px] font-label text-on-surface-variant/60 uppercase tracking-widest">
        {label}
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-xs text-on-surface-variant">
          {format(baseVal)} → {format(headVal)}
        </span>
      </div>
      <div className={cn("font-mono text-sm font-bold", colorClass)}>
        {arrow} {format(Math.abs(delta))}
        {baseVal !== 0 && (
          <span className="ml-2 text-xs font-normal">
            ({(pct * 100).toFixed(1)}%)
          </span>
        )}
      </div>
    </div>
  );
}

function PerCaseDiff({ base, head }: { base: RunDetail; head: RunDetail }) {
  // Build a map by case_id for O(1) lookup.
  const byId = useMemo(() => {
    const m = new Map<string, { base?: CaseScore; head?: CaseScore }>();
    for (const c of base.summary.cases) {
      m.set(c.case_id, { base: c, head: undefined });
    }
    for (const c of head.summary.cases) {
      const e = m.get(c.case_id) ?? { base: undefined, head: undefined };
      e.head = c;
      m.set(c.case_id, e);
    }
    return m;
  }, [base, head]);

  if (byId.size === 0) {
    return null;
  }

  return (
    <div className="rounded-2xl overflow-hidden" style={glassCard}>
      <div className="px-5 pt-4 pb-2">
        <h2 className="text-sm font-semibold text-on-surface">
          Per-case diff
        </h2>
      </div>
      <table className="w-full text-xs">
        <thead className="bg-white/5">
          <tr className="text-on-surface-variant/80">
            <th className="text-left px-4 py-2 font-label">Case</th>
            <th className="text-left px-4 py-2 font-label">Correctness</th>
            <th className="text-left px-4 py-2 font-label">Jaccard Δ</th>
            <th className="text-left px-4 py-2 font-label">Cost Δ</th>
            <th className="text-left px-4 py-2 font-label">Wall Δ</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(byId.entries()).map(([caseId, pair]) => {
            const b = pair.base;
            const h = pair.head;
            const correctnessFlip =
              b && h && b.correctness !== h.correctness;
            const jaccardDelta =
              (h?.tool_call_jaccard ?? 0) - (b?.tool_call_jaccard ?? 0);
            const costDelta = (h?.cost_usd ?? 0) - (b?.cost_usd ?? 0);
            const wallDelta = (h?.wall_seconds ?? 0) - (b?.wall_seconds ?? 0);
            return (
              <tr
                key={caseId}
                className="border-t border-white/5 hover:bg-white/2"
              >
                <td className="px-4 py-3 font-mono text-on-surface">
                  {caseId}
                </td>
                <td className="px-4 py-3">
                  <span className="text-on-surface-variant">
                    {b?.correctness == null
                      ? "n/a"
                      : b.correctness
                        ? "✓"
                        : "✗"}{" "}
                    →{" "}
                    {h?.correctness == null
                      ? "n/a"
                      : h.correctness
                        ? "✓"
                        : "✗"}
                    {correctnessFlip && (
                      <span
                        className={cn(
                          "ml-2 font-bold",
                          h?.correctness ? "text-tertiary" : "text-error",
                        )}
                      >
                        {h?.correctness ? "FIXED" : "REGRESSED"}
                      </span>
                    )}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono">
                  <span
                    className={cn(
                      Math.abs(jaccardDelta) < 0.05
                        ? "text-on-surface-variant"
                        : jaccardDelta > 0
                          ? "text-tertiary"
                          : "text-error",
                    )}
                  >
                    {jaccardDelta >= 0 ? "+" : ""}
                    {jaccardDelta.toFixed(2)}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono">
                  <span
                    className={cn(
                      Math.abs(costDelta) < 0.0001
                        ? "text-on-surface-variant"
                        : costDelta < 0
                          ? "text-tertiary"
                          : "text-error",
                    )}
                  >
                    {costDelta >= 0 ? "+" : ""}${costDelta.toFixed(4)}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono">
                  <span
                    className={cn(
                      Math.abs(wallDelta) < 0.5
                        ? "text-on-surface-variant"
                        : wallDelta < 0
                          ? "text-tertiary"
                          : "text-error",
                    )}
                  >
                    {wallDelta >= 0 ? "+" : ""}
                    {wallDelta.toFixed(1)}s
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
