"use client";

/**
 * /observability/cost
 *
 * Cost rollups derived from chat_turn_cost audit rows. Aggregates
 * by time window, by model, and by trigger (interactive chat vs
 * scheduled jobs). Operators can answer "what did this month
 * cost?" / "what does the chatbot trigger cost vs the daily-coverage
 * job?" / "is Vertex caching saving money?"
 *
 * Why query the audit log directly (vs a dedicated /cost API):
 * the audit rows ARE the cost data — every turn writes one. A
 * separate aggregation table would just be redundant precomputation.
 * For now, the page does sum-in-the-browser; if the audit log
 * grows past ~10k rows, we add an MCP-side /api/v1/observability/
 * cost-rollup endpoint.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { formatCostOrUnpriced, formatUsd } from "@/lib/model-pricing";
import {
  addRowToBucket,
  emptyBucket,
  readCostRow,
  type CostBucket,
} from "@/lib/cost-rows";

interface AuditRow {
  id: string | number;
  ts: string;
  action: string;
  target: string | null;
  // Audit table's trigger column (set by trigger_context
  // middleware: "chat", "job:<name>", "api", "operator", "unknown").
  trigger?: string | null;
  metadata: Record<string, unknown> | null;
}

interface AuditResponse {
  events: AuditRow[];
  count: number;
}

type WindowOption = "today" | "7d" | "30d" | "all";

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

/** Group-by axes for the breakdown view. `model` groups by the full
 *  `provider/model` ref, so the same model id under two providers stays apart. */
type GroupBy = "model" | "provider" | "session" | "job" | "callKind";

const GROUP_BY_LABELS: Record<GroupBy, string> = {
  provider: "Provider",
  model: "Model (provider/model)",
  callKind: "Call kind",
  session: "Session",
  job: "Job",
};

export default function CostRollupPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [windowChoice, setWindowChoice] = useState<WindowOption>("7d");
  const [groupBy, setGroupBy] = useState<GroupBy>("model");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const since = sinceFor(windowChoice);
      const sp = new URLSearchParams({
        action: "chat_turn_cost",
        limit: "5000",
      });
      if (since) sp.set("since", since);
      const r = await fetch(`/api/agent/audit?${sp.toString()}`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`audit fetch ${r.status}`);
      const data = (await r.json()) as AuditResponse;
      setRows(data.events ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [windowChoice]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stats = useMemo(() => aggregate(rows), [rows]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1300px] mx-auto px-8 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                payments
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Cost rollup
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9 max-w-2xl">
              Per-call cost from <code className="font-mono">chat_turn_cost</code>{" "}
              audit rows, by provider and model. Includes prompt-caching
              savings and cache-write cost. Pricing source: the per-model
              rates shown on the Models page. A call to a model with no known
              price is counted as unpriced and left out of the dollar totals.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {(
              [
                { key: "today" as const, label: "Today" },
                { key: "7d" as const, label: "Last 7d" },
                { key: "30d" as const, label: "Last 30d" },
                { key: "all" as const, label: "All time" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setWindowChoice(opt.key)}
                className={cn(
                  "px-3 py-1.5 rounded-full text-[11px] transition-colors",
                  windowChoice === opt.key
                    ? "bg-primary/15 text-primary border border-primary/30"
                    : "bg-white/5 text-on-surface-variant hover:text-on-surface border border-transparent",
                )}
              >
                {opt.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="ml-2 px-3 py-1.5 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
              style={glassCard}
              aria-label="Refresh"
            >
              <span className="material-symbols-outlined text-sm align-middle">
                refresh
              </span>
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {/* Hero stat — total */}
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {/* A window where no call had a price has no total: "unpriced", not $0. */}
          <StatCard
            label="Total cost"
            value={
              stats.calls > 0 && stats.unpricedCalls === stats.calls
                ? "unpriced"
                : formatUsd(stats.totalUsd)
            }
            sub={`${stats.calls.toLocaleString()} calls${
              stats.unpricedCalls > 0 && stats.unpricedCalls < stats.calls
                ? `, ${stats.unpricedCalls.toLocaleString()} unpriced not included`
                : ""
            }`}
            tone="primary"
          />
          <StatCard
            label="Unpriced calls"
            value={stats.unpricedCalls.toLocaleString()}
            sub={
              stats.unpricedCalls > 0
                ? "no known price; not in the total"
                : "every call priced"
            }
            tone={stats.unpricedCalls > 0 ? "secondary" : "neutral"}
          />
          <StatCard
            label="Cached savings"
            value={formatUsd(stats.totalSavings)}
            sub="Prompt cache"
            tone="secondary"
          />
          <StatCard
            label="Input tokens"
            value={stats.input.toLocaleString()}
            sub={`${stats.cached.toLocaleString()} cached, ${stats.cacheWrite.toLocaleString()} cache writes`}
            tone="neutral"
          />
          <StatCard
            label="Output tokens"
            value={stats.output.toLocaleString()}
            sub={`${stats.reasoning.toLocaleString()} of them reasoning`}
            tone="neutral"
          />
        </div>

        {/* Group-by toggle. Picks the axis the breakdown
            renders. All axes computed in one aggregator pass; the
            toggle is instant client-side. */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-label text-on-surface-variant/80 uppercase tracking-widest">
            Group by
          </span>
          {(Object.keys(GROUP_BY_LABELS) as GroupBy[]).map((axis) => (
            <button
              key={axis}
              type="button"
              onClick={() => setGroupBy(axis)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                groupBy === axis
                  ? "bg-primary-container/30 text-on-primary-container"
                  : "text-on-surface-variant hover:bg-white/5",
              )}
            >
              {GROUP_BY_LABELS[axis]}
            </button>
          ))}
        </div>

        {/* Breakdown — uses the current group-by axis */}
        <Section title={`By ${GROUP_BY_LABELS[groupBy].toLowerCase()}`}>
          {(() => {
            const bucket =
              groupBy === "provider"
                ? stats.byProvider
                : groupBy === "model"
                  ? stats.byModel
                  : groupBy === "callKind"
                    ? stats.byCallKind
                    : groupBy === "session"
                      ? stats.bySession
                      : stats.byJob;
            const entries = Object.entries(bucket).sort(
              (a, b) => b[1].usd - a[1].usd,
            );
            if (entries.length === 0) return <Empty />;
            return (
              <div className="grid gap-2">
                {entries.map(([key, m]) => (
                  <BreakdownRow
                    key={key}
                    label={
                      groupBy === "callKind"
                        ? key === "initial"
                          ? "Initial calls (operator prompt)"
                          : key === "followup"
                            ? "Tool-result follow-ups"
                            : key
                        : key
                    }
                    bucket={m}
                    proportionUsd={m.usd / Math.max(stats.totalUsd, 0.0000001)}
                  />
                ))}
              </div>
            );
          })()}
        </Section>

        {/* Recent rows */}
        <Section title={`Recent calls (${rows.length})`}>
          {rows.length === 0 ? (
            <Empty />
          ) : (
            <div
              className="rounded-2xl overflow-hidden"
              style={glassCard}
            >
              <div className="grid grid-cols-12 gap-2 px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/70 border-b border-outline-variant/10">
                <div className="col-span-2">Timestamp</div>
                <div className="col-span-1">Session</div>
                <div className="col-span-2">Model</div>
                <div className="col-span-1 text-right">Input</div>
                <div className="col-span-1 text-right">Output</div>
                <div className="col-span-1 text-right">Cached</div>
                <div className="col-span-1 text-right">Cache wr.</div>
                <div className="col-span-1 text-right">Reasoning</div>
                <div className="col-span-2 text-right">Cost</div>
              </div>
              <ul className="divide-y divide-outline-variant/10 max-h-[600px] overflow-y-auto">
                {rows.slice(0, 200).map((r) => {
                  const row = readCostRow(r);
                  const session = (r.target ?? "").replace(/^session:/, "");
                  return (
                    <li
                      key={String(r.id)}
                      className="grid grid-cols-12 gap-2 px-4 py-2 text-xs items-center hover:bg-white/5"
                    >
                      <div className="col-span-2 font-mono text-[11px] text-on-surface-variant/80">
                        {r.ts.slice(0, 19)}
                      </div>
                      <div className="col-span-1 truncate">
                        {session ? (
                          <Link
                            href={`/?session=${session}`}
                            className="font-mono text-[11px] text-primary hover:underline"
                          >
                            {session.slice(0, 8)}…
                          </Link>
                        ) : (
                          "—"
                        )}
                      </div>
                      <div
                        className="col-span-2 truncate font-mono text-[11px] text-on-surface-variant"
                        title={row.modelRef}
                      >
                        {row.modelRef}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {row.input.toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {row.output.toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-tertiary">
                        {row.cached.toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {row.cacheWrite.toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {row.reasoning.toLocaleString()}
                      </div>
                      <div
                        className={cn(
                          "col-span-2 text-right font-mono text-[11px]",
                          row.priced ? "text-on-surface" : "text-on-surface-variant/70",
                        )}
                      >
                        {formatCostOrUnpriced(row.usd)}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {rows.length > 200 && (
                <div className="px-4 py-2 text-[10px] text-on-surface-variant/60 border-t border-outline-variant/10">
                  Showing 200 most recent of {rows.length}. Filter by
                  window above or query{" "}
                  <Link
                    href="/observability/events?q=action:chat_turn_cost"
                    className="link"
                  >
                    /observability/events
                  </Link>{" "}
                  for the full audit log.
                </div>
              )}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

// ─── Helpers + sub-components ──────────────────────────────────────

function sinceFor(w: WindowOption): string | null {
  if (w === "all") return null;
  const d = new Date();
  if (w === "today") d.setUTCHours(0, 0, 0, 0);
  else if (w === "7d") d.setUTCDate(d.getUTCDate() - 7);
  else if (w === "30d") d.setUTCDate(d.getUTCDate() - 30);
  return d.toISOString();
}

function aggregate(rows: AuditRow[]) {
  const out = {
    ...emptyBucket(),
    totalUsd: 0,
    totalSavings: 0,
    byModel: {} as Record<string, CostBucket>,
    byCallKind: {} as Record<string, CostBucket>,
    // Additional group-by axes for the toggle. Operators
    // pick which axis the breakdown view renders; all axes computed
    // in one pass so toggle is instant.
    byProvider: {} as Record<string, CostBucket>,
    bySession: {} as Record<string, CostBucket>,
    byJob: {} as Record<string, CostBucket>,
  };
  const add = (bucket: Record<string, CostBucket>, key: string, row: ReturnType<typeof readCostRow>) =>
    addRowToBucket((bucket[key] ??= emptyBucket()), row);
  for (const r of rows) {
    // readCostRow applies the defaults for rows written before the provider
    // fields existed (provider vertex, model_ref provider/model, priced when
    // there is a figure) and never yields NaN.
    const row = readCostRow(r);
    addRowToBucket(out, row);
    out.totalSavings += row.savingsUsd;
    add(out.byModel, row.modelRef, row);
    add(out.byCallKind, row.callKind, row);
    add(out.byProvider, row.provider, row);
    // Session: target is "session:<uuid>" for chat_turn_cost rows.
    const target = r.target ?? "";
    const sessionMatch = /^session:(.+)$/.exec(target);
    add(
      out.bySession,
      sessionMatch ? `session:${sessionMatch[1].slice(0, 12)}…` : "session:(unknown)",
      row,
    );
    // Job: trigger_context middleware sets "job:<name>" when scheduler
    // dispatches; chat-driven turns get "(interactive chat)".
    const trigger = r.trigger ?? "";
    const jobMatch = /^job:(.+)$/.exec(trigger);
    add(out.byJob, jobMatch ? `job:${jobMatch[1]}` : "(interactive chat)", row);
  }
  return { ...out, totalUsd: out.usd };
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "primary" | "secondary" | "neutral";
}) {
  const valueClass =
    tone === "primary"
      ? "text-primary"
      : tone === "secondary"
        ? "text-secondary"
        : "text-on-surface";
  return (
    <div
      className="rounded-2xl p-4 space-y-1"
      style={glassCard}
    >
      <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60">
        {label}
      </p>
      <p className={cn("text-2xl font-headline font-bold", valueClass)}>
        {value}
      </p>
      <p className="text-[11px] text-on-surface-variant/60 font-mono">
        {sub}
      </p>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h2 className="text-xs font-label uppercase tracking-widest text-on-surface-variant/60">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Empty() {
  return (
    <div
      className="text-center py-8 rounded-2xl text-sm text-on-surface-variant"
      style={glassCard}
    >
      No data in this window.
    </div>
  );
}

function BreakdownRow({
  label,
  bucket,
  proportionUsd,
}: {
  label: string;
  bucket: CostBucket;
  proportionUsd: number;
}) {
  const allUnpriced = bucket.calls > 0 && bucket.unpricedCalls === bucket.calls;
  return (
    <div className="rounded-2xl p-3 flex items-center gap-3" style={glassCard}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {label}
          </span>
          <span className="text-[10px] font-mono text-on-surface-variant/60">
            {bucket.calls} call{bucket.calls === 1 ? "" : "s"}
          </span>
          {bucket.unpricedCalls > 0 && !allUnpriced && (
            <span className="text-[10px] font-mono text-secondary">
              {bucket.unpricedCalls} unpriced
            </span>
          )}
          {(bucket.cacheWrite > 0 || bucket.reasoning > 0) && (
            <span className="text-[10px] font-mono text-on-surface-variant/60">
              {bucket.cacheWrite > 0
                ? `${bucket.cacheWrite.toLocaleString()} cache writes`
                : ""}
              {bucket.cacheWrite > 0 && bucket.reasoning > 0 ? ", " : ""}
              {bucket.reasoning > 0
                ? `${bucket.reasoning.toLocaleString()} reasoning`
                : ""}
            </span>
          )}
        </div>
        <div
          className="w-full h-1.5 rounded-full overflow-hidden"
          style={{ background: "rgba(140, 145, 157, 0.15)" }}
          aria-hidden="true"
        >
          <div
            className="h-full bg-primary rounded-full transition-[width]"
            style={{ width: `${Math.min(100, proportionUsd * 100)}%` }}
          />
        </div>
      </div>
      <span className="font-mono text-sm text-on-surface shrink-0">
        {allUnpriced ? "unpriced" : formatUsd(bucket.usd)}
      </span>
    </div>
  );
}
