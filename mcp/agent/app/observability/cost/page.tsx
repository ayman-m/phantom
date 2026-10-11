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
import { formatUsd } from "@/lib/model-pricing";

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

/** Group-by axes for the breakdown view. */
type GroupBy = "model" | "provider" | "session" | "job" | "callKind";

const GROUP_BY_LABELS: Record<GroupBy, string> = {
  provider: "Provider",
  model: "Model",
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
              Per-turn cost from <code className="font-mono">chat_turn_cost</code>{" "}
              audit rows. Includes Vertex prompt-caching savings.
              Pricing source: Vertex AI public pricing as of 2026-05.
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
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <StatCard
            label="Total cost"
            value={formatUsd(stats.totalUsd)}
            sub={`${stats.calls.toLocaleString()} calls`}
            tone="primary"
          />
          <StatCard
            label="Cached savings"
            value={formatUsd(stats.totalSavings)}
            sub="Vertex prompt cache"
            tone="secondary"
          />
          <StatCard
            label="Input tokens"
            value={stats.input.toLocaleString()}
            sub={`${stats.cached.toLocaleString()} cached`}
            tone="neutral"
          />
          <StatCard
            label="Output tokens"
            value={stats.output.toLocaleString()}
            sub="model-emitted"
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
                    usd={m.usd}
                    calls={m.calls}
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
                <div className="col-span-3">Session</div>
                <div className="col-span-2">Model</div>
                <div className="col-span-1 text-right">Input</div>
                <div className="col-span-1 text-right">Output</div>
                <div className="col-span-1 text-right">Cached</div>
                <div className="col-span-2 text-right">Cost</div>
              </div>
              <ul className="divide-y divide-outline-variant/10 max-h-[600px] overflow-y-auto">
                {rows.slice(0, 200).map((r) => {
                  const m = r.metadata ?? {};
                  const session = (r.target ?? "").replace(/^session:/, "");
                  return (
                    <li
                      key={String(r.id)}
                      className="grid grid-cols-12 gap-2 px-4 py-2 text-xs items-center hover:bg-white/5"
                    >
                      <div className="col-span-2 font-mono text-[11px] text-on-surface-variant/80">
                        {r.ts.slice(0, 19)}
                      </div>
                      <div className="col-span-3 truncate">
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
                      <div className="col-span-2 truncate font-mono text-[11px] text-on-surface-variant">
                        {(m["model"] as string) ?? "—"}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {Number(m["input_tokens"] ?? 0).toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-on-surface-variant">
                        {Number(m["output_tokens"] ?? 0).toLocaleString()}
                      </div>
                      <div className="col-span-1 text-right font-mono text-[11px] text-tertiary">
                        {Number(m["cached_input_tokens"] ?? 0).toLocaleString()}
                      </div>
                      <div className="col-span-2 text-right font-mono text-[11px] text-on-surface">
                        {formatUsd(Number(m["cost_usd"] ?? 0))}
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
    calls: 0,
    input: 0,
    cached: 0,
    output: 0,
    totalUsd: 0,
    totalSavings: 0,
    byModel: {} as Record<string, { usd: number; calls: number }>,
    byCallKind: {} as Record<string, { usd: number; calls: number }>,
    // Additional group-by axes for the toggle. Operators
    // pick which axis the breakdown view renders; all axes computed
    // in one pass so toggle is instant.
    byProvider: {} as Record<string, { usd: number; calls: number }>,
    bySession: {} as Record<string, { usd: number; calls: number }>,
    byJob: {} as Record<string, { usd: number; calls: number }>,
  };
  for (const r of rows) {
    const m = r.metadata ?? {};
    out.calls += 1;
    out.input += Number(m["input_tokens"] ?? 0);
    out.cached += Number(m["cached_input_tokens"] ?? 0);
    out.output += Number(m["output_tokens"] ?? 0);
    const usd = Number(m["cost_usd"] ?? 0);
    out.totalUsd += usd;
    const components = m["cost_components"] as
      | Record<string, number>
      | undefined;
    out.totalSavings += Number(components?.["cached_savings_usd"] ?? 0);
    const model = (m["model"] as string) ?? "unknown";
    if (!out.byModel[model]) out.byModel[model] = { usd: 0, calls: 0 };
    out.byModel[model].usd += usd;
    out.byModel[model].calls += 1;
    const kind = (m["call_kind"] as string) ?? "unknown";
    if (!out.byCallKind[kind]) out.byCallKind[kind] = { usd: 0, calls: 0 };
    out.byCallKind[kind].usd += usd;
    out.byCallKind[kind].calls += 1;
    // Provider derived from model prefix (no explicit
    // provider column; cheap heuristic matching Phantom's catalog).
    const provider = providerFromModel(model);
    if (!out.byProvider[provider]) out.byProvider[provider] = { usd: 0, calls: 0 };
    out.byProvider[provider].usd += usd;
    out.byProvider[provider].calls += 1;
    // Session: target is "session:<uuid>" for chat_turn_cost rows.
    const target = r.target ?? "";
    const sessionMatch = /^session:(.+)$/.exec(target);
    const sessionKey = sessionMatch
      ? `session:${sessionMatch[1].slice(0, 12)}…`
      : "session:(unknown)";
    if (!out.bySession[sessionKey]) out.bySession[sessionKey] = { usd: 0, calls: 0 };
    out.bySession[sessionKey].usd += usd;
    out.bySession[sessionKey].calls += 1;
    // Job: trigger_context middleware sets "job:<name>" when scheduler
    // dispatches; chat-driven turns get "(interactive chat)".
    const trigger = r.trigger ?? "";
    const jobMatch = /^job:(.+)$/.exec(trigger);
    const jobKey = jobMatch ? `job:${jobMatch[1]}` : "(interactive chat)";
    if (!out.byJob[jobKey]) out.byJob[jobKey] = { usd: 0, calls: 0 };
    out.byJob[jobKey].usd += usd;
    out.byJob[jobKey].calls += 1;
  }
  return out;
}

/** Map a model id to its provider for the byProvider breakdown.
 *  Cheap prefix match — no explicit provider column in audit metadata. */
function providerFromModel(model: string): string {
  if (!model || model === "unknown") return "unknown";
  if (model.startsWith("gemini-")) return "vertex / gemini";
  if (model.startsWith("claude-")) return "anthropic";
  if (model.startsWith("gpt-") || model.startsWith("o1-")) return "openai";
  return model.split("-")[0] || "unknown";
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
  usd,
  calls,
  proportionUsd,
}: {
  label: string;
  usd: number;
  calls: number;
  proportionUsd: number;
}) {
  return (
    <div className="rounded-2xl p-3 flex items-center gap-3" style={glassCard}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {label}
          </span>
          <span className="text-[10px] font-mono text-on-surface-variant/60">
            {calls} call{calls === 1 ? "" : "s"}
          </span>
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
        {formatUsd(usd)}
      </span>
    </div>
  );
}
