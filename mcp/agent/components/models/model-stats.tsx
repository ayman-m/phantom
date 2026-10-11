"use client";

import { useEffect, useState } from "react";
import { getModelStats } from "@/lib/api/models";
import type { ModelStats } from "@/lib/api/types";

const numberFormatter = new Intl.NumberFormat("en-US");

function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return String(tokens);
}

function formatDuration(ms: number): string {
  if (ms < 1_000) return `${Math.round(ms)}ms`;
  return `${(ms / 1_000).toFixed(1)}s`;
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

interface ModelStatsProps {
  provider: string;
  model: string;
}

export function ModelStatsPanel({ provider, model }: ModelStatsProps) {
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchStats() {
      setLoading(true);
      const result = await getModelStats(model, {
        provider,
        timeWindow: "7d",
      });
      if (!cancelled && result.ok) {
        setStats(result.data);
      }
      if (!cancelled) {
        setLoading(false);
      }
    }

    fetchStats();
    return () => {
      cancelled = true;
    };
  }, [provider, model]);

  const totalTokens =
    stats != null
      ? stats.total_input_tokens + stats.total_output_tokens
      : 0;

  // Progress bar: fill proportional to runs (cap at 100 for visual scaling).
  const progressWidth =
    stats != null && stats.total_runs > 0
      ? Math.min((stats.total_runs / 100) * 100, 100)
      : 0;

  const hasData = stats != null && stats.total_runs > 0;

  return (
    <section className="space-y-4">
      <h3 className="font-headline text-lg font-bold text-on-surface px-1">
        Performance Metrics
      </h3>
      <div
        className="rounded-2xl p-6 space-y-6"
        style={{
          background: "var(--glass-bg-strong)",
          backdropFilter: "blur(12px)",
          border: "0.5px solid var(--glass-border)",
        }}
      >
        {/* Total Runs */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
              Total Runs
            </div>
            <div className="text-3xl font-headline font-bold text-on-surface">
              {loading
                ? "..."
                : hasData
                  ? numberFormatter.format(stats.total_runs)
                  : "—"}
            </div>
          </div>
          <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="material-symbols-outlined text-primary">
              analytics
            </span>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden">
          <div
            className="h-full bg-primary shadow-[0_0_8px_#a7c8ff] transition-all duration-700"
            style={{ width: `${progressWidth}%` }}
          />
        </div>

        {/* Token count + Last Used */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <div className="text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
              Total Tokens
            </div>
            <div className="text-xl font-headline font-bold text-on-surface">
              {loading
                ? "..."
                : hasData
                  ? formatTokenCount(totalTokens)
                  : "—"}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
              Last Used
            </div>
            <div className="text-xl font-headline font-bold text-on-surface">
              {loading
                ? "..."
                : hasData && stats.last_used_at
                  ? formatRelativeTime(stats.last_used_at)
                  : "—"}
            </div>
          </div>
        </div>

        {/* Avg Duration */}
        {hasData && stats.avg_duration_ms > 0 && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <div className="text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
                Avg Duration
              </div>
              <div className="text-xl font-headline font-bold text-on-surface">
                {formatDuration(stats.avg_duration_ms)}
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
                Input / Output
              </div>
              <div className="text-sm font-mono text-on-surface-variant">
                {formatTokenCount(stats.total_input_tokens)} /{" "}
                {formatTokenCount(stats.total_output_tokens)}
              </div>
            </div>
          </div>
        )}

        <p className="text-[10px] text-on-surface-variant/50 uppercase tracking-widest text-center">
          {hasData ? "Last 7 days" : "Usage data available after first run"}
        </p>
      </div>
    </section>
  );
}
