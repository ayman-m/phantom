"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import type {
  InteractionPattern,
  ModelInfo,
  ModelPricingInfo,
} from "@/lib/api/types";
import { providerName } from "@/lib/model-catalog";
import { defaultSourceHint, setInstallDefaultModel } from "@/lib/set-default-model";

/**
 * Phantom model detail page. Spark fetches a single model via
 * a per-model endpoint; phantom serves the whole registry from
 * /api/agent/models (the curated catalog merged with each provider's live
 * list), so we fetch the list and find the requested entry client-side. Keeps
 * the detail panel available without a separate per-model endpoint.
 *
 * Shows where each fact came from: availability, whether the entry was seen on
 * the provider's live list (and when), the price and the date it was checked,
 * and the lifecycle. Gemini models get a Verify action, because Vertex has no
 * model list to prove they are enabled.
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
  async_job: {
    label: "Async Job",
    description: "Submitted as a job and polled asynchronously.",
    icon: "schedule",
    colorClass: "text-orange-400",
  },
};

const AVAILABILITY_LABEL: Record<string, string> = {
  available: "Available",
  deprecated: "Deprecated",
  unverified: "Unverified",
  unpriced: "Unpriced",
  unavailable: "Not visible to this key",
  not_configured: "Provider not configured",
  retired: "Retired",
};

const SOURCE_LABEL: Record<string, string> = {
  live: "Provider's live list",
  curated: "Built-in table",
  "live+curated": "Provider's live list, with the built-in table",
};

function formatContextWindow(tokens: number | null | undefined): string {
  if (!tokens || tokens <= 0) return "—";
  if (tokens >= 1_000_000) return `${+(tokens / 1_000_000).toFixed(2)}M tokens`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K tokens`;
  return `${tokens} tokens`;
}

function usd(v: number | undefined): string {
  return v === undefined ? "—" : `$${+v.toFixed(4)}`;
}

const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

function PricingTable({ pricing }: { pricing: ModelPricingInfo }) {
  const rows: Array<[string, string]> = [
    ["Input", usd(pricing.inputPerM)],
    ["Output", usd(pricing.outputPerM)],
    ["Cache read", usd(pricing.cacheReadPerM)],
  ];
  if (pricing.cacheWrite5mPerM !== undefined) {
    rows.push([
      pricing.cacheWrite1hPerM !== undefined ? "Cache write (5 minutes)" : "Cache write",
      usd(pricing.cacheWrite5mPerM),
    ]);
  }
  if (pricing.cacheWrite1hPerM !== undefined) rows.push(["Cache write (1 hour)", usd(pricing.cacheWrite1hPerM)]);
  return (
    <div className="space-y-3">
      <table className="text-sm">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="pr-8 py-1 text-on-surface-variant">{label}</td>
              <td className="py-1 font-mono text-on-surface">{value}</td>
              <td className="py-1 pl-2 text-xs text-outline">per million tokens</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pricing.longContext && (
        <p className="text-xs text-on-surface-variant">
          A prompt over {pricing.longContext.aboveInputTokens.toLocaleString()} tokens is billed at{" "}
          {pricing.longContext.inputMult}x the input and cache rates and{" "}
          {pricing.longContext.outputMult}x the output rate for the whole request.
        </p>
      )}
    </div>
  );
}

export default function ModelDetailPage() {
  const params = useParams<{ model: string }>();
  const searchParams = useSearchParams();
  const requestedModel = decodeURIComponent(params.model || "");
  const requestedProvider = searchParams.get("provider") || "";

  const [model, setModel] = useState<ModelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Bumped after the default changes so the entry is fetched again.
  const [reloadKey, setReloadKey] = useState(0);
  const [verify, setVerify] = useState<
    | { state: "idle" }
    | { state: "running" }
    | { state: "done"; ok: boolean; message: string }
  >({ state: "idle" });

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
  }, [requestedModel, requestedProvider, reloadKey]);

  const runVerify = useCallback(async () => {
    if (!model) return;
    setVerify({ state: "running" });
    try {
      const r = await fetch("/api/agent/providers/vertex/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model.model }),
      });
      const body = (await r.json()) as { status?: string; message?: string };
      setVerify({
        state: "done",
        ok: body.status === "success",
        message: body.message || (r.ok ? "Done." : `The check failed (HTTP ${r.status}).`),
      });
    } catch {
      setVerify({ state: "done", ok: false, message: "The check could not be completed." });
    }
  }, [model]);

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
              : `No model in the registry matched ${requestedModel}${
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
  const canVerify = model.provider === "vertex" && (model.kind ?? "chat") === "chat";
  // A chat model chat can run on, unless it is already the install's own default.
  const canSetDefault =
    (model.kind ?? "chat") === "chat" &&
    model.selectable &&
    !(model.isDefault && model.defaultSource === "default");

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
            <code className="text-xs text-outline font-mono">{model.ref}</code>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className="px-2 py-0.5 rounded-md bg-surface-container text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                {providerName(model.provider)}
              </span>
              {model.isDefault && (
                <span
                  className="px-2 py-0.5 rounded-md bg-primary-container text-[10px] font-bold uppercase tracking-wider text-on-primary-container"
                  title={defaultSourceHint(model.defaultSource)}
                >
                  {model.defaultSource === "derived" ? "Default (derived)" : "Default"}
                </span>
              )}
              {model.launchStage &&
                model.launchStage !== "GA" &&
                model.launchStage !== "DEPRECATED" &&
                model.launchStage !== "RETIRED" && (
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
          {canSetDefault && (
            <button
              type="button"
              onClick={async () => {
                if (await setInstallDefaultModel(model.ref, model.displayName || model.model)) {
                  setReloadKey((k) => k + 1);
                }
              }}
              className="shrink-0 px-4 py-2 rounded-lg text-xs font-bold font-label uppercase tracking-wider text-primary border border-primary/30 hover:bg-primary/10 transition-colors"
            >
              Set as default
            </button>
          )}
        </div>
        {model.isDefault && model.defaultSource === "derived" && (
          <p className="mt-4 text-xs text-on-surface-variant">
            No default model is set. This model serves because it is the
            recommended model of the first configured provider; set a default
            to pin one.
          </p>
        )}
      </header>

      {/* Stats */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
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
            Max output
          </p>
          <p className="text-xl font-bold font-headline mt-1">
            {formatContextWindow(model.maxOutput)}
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

      {/* Availability and source */}
      <section className="rounded-2xl p-6 space-y-3" style={glassStyle}>
        <h2 className="font-headline text-lg font-bold">Availability</h2>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-outline">Status</dt>
            <dd className="text-on-surface">
              {AVAILABILITY_LABEL[model.availability] ?? model.availability}
              {model.selectable ? "" : " (not selectable)"}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-outline">Source</dt>
            <dd className="text-on-surface">{SOURCE_LABEL[model.source ?? "curated"]}</dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-outline">Last refresh</dt>
            <dd className="text-on-surface">
              {model.liveSeenAt
                ? new Date(model.liveSeenAt).toLocaleString()
                : "Not seen on a live list"}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-outline">Lifecycle</dt>
            <dd className="text-on-surface">
              {model.lifecycle?.stage ?? "ga"}
              {model.lifecycle?.retiresAt
                ? `, retires ${model.lifecycle.retiresAt.slice(0, 10)}`
                : ""}
            </dd>
          </div>
        </dl>
        {model.reason && (
          <p className="text-sm text-on-surface-variant">{model.reason}</p>
        )}
        {model.refreshError && (
          <p className="text-xs text-error">
            The last refresh failed: {model.refreshError}
          </p>
        )}
        {canVerify && (
          <div className="flex items-center gap-3 flex-wrap pt-2">
            <button
              type="button"
              onClick={runVerify}
              disabled={verify.state === "running"}
              className="px-5 py-2.5 rounded-xl font-label text-xs uppercase tracking-wider font-bold text-on-surface bg-white/5 hover:bg-white/10 transition-all disabled:opacity-60"
              aria-label={`Verify ${model.displayName || model.model} is enabled`}
            >
              {verify.state === "running" ? "Verifying…" : "Verify"}
            </button>
            <p className="text-xs text-on-surface-variant max-w-md">
              Asks Google for a token count on this model. It generates nothing
              and costs nothing.
            </p>
            {verify.state === "done" && (
              <span
                role="status"
                className={`text-xs font-bold ${verify.ok ? "text-secondary" : "text-error"}`}
              >
                {verify.message}
              </span>
            )}
          </div>
        )}
      </section>

      {/* Pricing */}
      {(model.kind ?? "chat") === "chat" && (
        <section className="rounded-2xl p-6 space-y-3" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold">Pricing</h2>
          {model.priced && model.pricing ? (
            <>
              <PricingTable pricing={model.pricing} />
              <p className="text-xs text-on-surface-variant">
                {model.pricingVerified
                  ? `Checked against the vendor's price page: ${model.pricingVerified}.`
                  : ""}
                {model.pricingValidUntil
                  ? ` Valid through ${model.pricingValidUntil}.`
                  : ""}
              </p>
              {model.pricingNote && (
                <p className="text-xs text-on-surface-variant">{model.pricingNote}</p>
              )}
            </>
          ) : (
            <p className="text-sm text-on-surface-variant">
              The cost of this model is not tracked, so its calls show no
              dollar figure.
              {model.pricingNote ? ` ${model.pricingNote}` : ""}
            </p>
          )}
        </section>
      )}

      {model.unverified && model.unverified.length > 0 && (
        <section className="rounded-2xl p-6 space-y-2" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold">Not confirmed</h2>
          <p className="text-sm text-on-surface-variant">
            The built-in table could not confirm these facts from an official
            source: {model.unverified.join(", ")}.
          </p>
        </section>
      )}

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
