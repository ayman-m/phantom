"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import type { ModelInfo, InteractionPattern } from "@/lib/api/types";

/**
 * Phantom model detail page — simplified version of the Spark detail
 * route. Spark fetches a single model via /api/v1/models/{id} and
 * /api/v1/config (for the default-model badge); phantom serves a
 * static catalog from /api/agent/models, so we fetch the whole list
 * and find the requested entry client-side. Keeps the detail panel
 * available without needing a separate per-model endpoint.
 */

const INTERACTION_PATTERN_INFO: Record<
  InteractionPattern,
  { label: string; description: string; icon: string; colorClass: string }
> = {
  streaming_api: {
    label: "Streaming API",
    description: "Responses streamed token-by-token in real time.",
    icon: "stream",
    colorClass: "text-primary",
  },
  cli_tool: {
    label: "CLI Tool",
    description: "Invoked via a command-line interface in a Docker container.",
    icon: "terminal",
    colorClass: "text-tertiary",
  },
  async_job: {
    label: "Async Job",
    description: "Submitted as a job and polled asynchronously.",
    icon: "schedule",
    colorClass: "text-orange-400",
  },
  interactive_session: {
    label: "Interactive Session",
    description: "Maintains conversational context across turns.",
    icon: "chat",
    colorClass: "text-secondary",
  },
};

function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M tokens`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K tokens`;
  if (tokens > 0) return `${tokens} tokens`;
  return "—";
}

const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function ModelDetailPage() {
  const params = useParams<{ model: string }>();
  const searchParams = useSearchParams();
  const requestedModel = decodeURIComponent(params.model || "");
  const requestedProvider = searchParams.get("provider") || "";

  const [model, setModel] = useState<ModelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/agent/models", { cache: "no-store" });
        if (!r.ok) throw new Error(`models ${r.status}`);
        const list = (await r.json()) as ModelInfo[];
        if (cancelled) return;
        const found =
          list.find(
            (m) =>
              m.model === requestedModel &&
              (!requestedProvider || m.provider === requestedProvider),
          ) ?? null;
        setModel(found);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestedModel, requestedProvider]);

  if (loading) {
    return (
      <div className="p-8 max-w-5xl mx-auto">
        <p className="text-sm text-on-surface-variant">Loading model…</p>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="p-8 max-w-5xl mx-auto">
        <div className="rounded-2xl p-8" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold mb-2">
            Model not found
          </h2>
          <p className="text-sm text-on-surface-variant mb-4">
            {error
              ? error
              : `No model in the catalog matched ${requestedModel}${
                  requestedProvider ? ` (provider: ${requestedProvider})` : ""
                }.`}
          </p>
          <Link
            href="/models"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold font-headline bg-primary-container text-on-primary-container hover:shadow-[0_0_15px_rgba(25,99,179,0.3)] transition-all"
          >
            <span className="material-symbols-outlined text-[16px]">arrow_back</span>
            Back to Models
          </Link>
        </div>
      </div>
    );
  }

  const patterns = model.interactionPatterns ?? [];

  return (
    <div className="p-8 pb-32 max-w-5xl mx-auto space-y-8">
      {/* Breadcrumb */}
      <Link
        href="/models"
        className="inline-flex items-center gap-2 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
      >
        <span className="material-symbols-outlined text-[16px]">arrow_back</span>
        Models
      </Link>

      {/* Header */}
      <header className="rounded-2xl p-8" style={glassStyle}>
        <div className="flex items-start gap-6">
          <div className="w-16 h-16 rounded-2xl bg-primary-container/20 flex items-center justify-center text-primary shrink-0">
            <span className="material-symbols-outlined text-3xl">
              {model.kind === "embedding"
                ? "scatter_plot"
                : model.kind === "image"
                ? "image"
                : model.kind === "voice"
                ? "graphic_eq"
                : "auto_awesome"}
            </span>
          </div>
          <div className="flex-1">
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              {model.displayName || model.model}
            </h1>
            <code className="text-xs text-outline font-mono">{model.model}</code>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className="px-2 py-0.5 rounded-md bg-surface-container text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                {model.provider}
              </span>
              {model.launchStage && model.launchStage !== "GA" && (
                <span
                  className="px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider"
                  style={{
                    background: "rgba(255, 175, 0, 0.15)",
                    color: "#ffc94f",
                    border: "1px solid rgba(255, 175, 0, 0.3)",
                  }}
                >
                  {model.launchStage.replace(/_/g, " ")}
                </span>
              )}
              <span className="px-2 py-0.5 rounded-md bg-surface-container text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                {model.kind || "chat"}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Stats */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl p-5" style={glassStyle}>
          <p className="text-[10px] uppercase tracking-wider text-outline">
            Context Window
          </p>
          <p className="text-xl font-bold font-headline mt-1">
            {formatContextWindow(model.contextWindow)}
          </p>
        </div>
        <div className="rounded-xl p-5" style={glassStyle}>
          <p className="text-[10px] uppercase tracking-wider text-outline">
            Thinking
          </p>
          <p className="text-xl font-bold font-headline mt-1">
            {model.supportsThinking ? "Supported" : "—"}
          </p>
        </div>
        <div className="rounded-xl p-5" style={glassStyle}>
          <p className="text-[10px] uppercase tracking-wider text-outline">
            Tool calling
          </p>
          <p className="text-xl font-bold font-headline mt-1">
            {model.supportsTools ? "Supported" : "—"}
          </p>
        </div>
      </section>

      {/* Interaction patterns */}
      {patterns.length > 0 && (
        <section className="rounded-2xl p-6" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold mb-4">
            Interaction patterns
          </h2>
          <div className="space-y-3">
            {patterns.map((pattern) => {
              const info = INTERACTION_PATTERN_INFO[pattern];
              if (!info) return null;
              return (
                <div key={pattern} className="flex items-start gap-4">
                  <span
                    className={`material-symbols-outlined ${info.colorClass} text-2xl shrink-0`}
                  >
                    {info.icon}
                  </span>
                  <div>
                    <p className="font-medium text-sm">{info.label}</p>
                    <p className="text-xs text-on-surface-variant mt-1">
                      {info.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
