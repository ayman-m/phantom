"use client";

import type * as React from "react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { RetryButton } from "@/components/retry-button";
import { fetchModelCatalog } from "@/lib/model-catalog";
import { defaultSourceHint, setInstallDefaultModel } from "@/lib/set-default-model";
import type {
  ModelInfo,
  InteractionPattern,
  ModelKind,
} from "@/lib/api/types";

/**
 * Phantom models page — ported from spark/services/ui's /models, with two
 * phantom-specific shifts:
 *   1. **Endpoints**: hits /api/agent/models, the model registry (curated
 *      catalog merged with each provider's live model list), instead of
 *      Spark's gateway-side catalog. The default badge comes from the
 *      registry's `isDefault`.
 *   2. **Mode**: Server Component → Client Component. Spark's version
 *      reads cookies via next/headers; phantom uses the standard auth
 *      cookie automatically attached to fetch(). Switching to a client
 *      component also makes the tab-routing (?tab=embedding) read-only
 *      via useSearchParams without a server roundtrip.
 */

const KNOWN_PROVIDERS = [
  { id: "vertex", label: "Google Vertex AI", icon: "diamond" },
  { id: "anthropic", label: "Anthropic", icon: "psychology" },
  { id: "openai", label: "OpenAI", icon: "smart_toy" },
] as const;

// ── Tabs ────────────────────────────────────────────────────────────────────
//
// The /models page splits its content across 5 tabs, each filtering the
// same underlying /api/agent/models response by kind.
// Tab state lives in the URL (`?tab=embedding`) so tabs are bookmarkable,
// back-button aware, and the page can stay a Server Component.

type TabId = "chat" | "embedding" | "image" | "voice";

const TABS: {
  id: TabId;
  label: string;
  icon: string;
  emptyHint: string;
}[] = [
  {
    id: "chat",
    label: "Chat",
    icon: "chat_bubble",
    emptyHint:
      "No chat models discovered. Add credentials for Google Vertex AI, Anthropic or OpenAI in Providers.",
  },
  {
    id: "embedding",
    label: "Embedding",
    icon: "hub",
    emptyHint:
      "No embedding models discovered. Google text-embedding-005 and gemini-embedding-001 show up here once Vertex AI is configured.",
  },
  {
    id: "image",
    label: "Image",
    icon: "image",
    emptyHint:
      "No image models discovered. Google Imagen appears here when Vertex AI is configured.",
  },
  {
    id: "voice",
    label: "Voice",
    icon: "graphic_eq",
    emptyHint:
      "No voice models discovered. Whisper, TTS, and Chirp appear here once their providers are configured.",
  },
];

/**
 * Decide which tab a model belongs in. One model → exactly one tab.
 */
function tabForModel(model: ModelInfo): TabId {
  switch (model.kind ?? "chat") {
    case "embedding":
      return "embedding";
    case "image":
      return "image";
    case "voice":
      return "voice";
    default:
      return "chat";
  }
}

type ProviderGroup = {
  id: string;
  label: string;
  icon: string;
  models: ModelInfo[];
  status: "connected" | "disconnected";
};

function formatContextWindow(tokens: number): string {
  if (!tokens || tokens <= 0) return "—";
  if (tokens >= 1_000_000) return `${+(tokens / 1_000_000).toFixed(2)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K`;
  return `${tokens}`;
}

/** "$4 / $20" per million input / output tokens, or null when unpriced. */
function formatPriceLine(model: ModelInfo): string | null {
  if (!model.priced || !model.pricing) return null;
  const n = (v: number) => `$${+v.toFixed(4)}`;
  return `${n(model.pricing.inputPerM)} / ${n(model.pricing.outputPerM)}`;
}

// Pattern badges: theme-aware tones rather than the M3 "fixed"
// variants (which are the same in dark + light and read as
// washed-out on the cream bg). Each badge uses its own hue family
// scaled to readable contrast on either background.
const PATTERN_BADGE: Record<InteractionPattern, { label: string; color: string }> = {
  streaming_api: { label: "API", color: "bg-primary/10 text-primary border-primary/30" },
  async_job: { label: "Async", color: "bg-orange-500/10 text-orange-600 border-orange-500/30" },
};

function isValidTab(value: string | undefined): value is TabId {
  return TABS.some((t) => t.id === value);
}

export default function ModelsPage() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab") ?? undefined;
  const activeTab: TabId = isValidTab(tabParam) ? tabParam : "chat";

  const [allModels, setAllModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<{ message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  // Bumped after the default changes so the list is fetched again.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        // Same fetcher as the /jobs/new Model dropdown (one registry).
        const data = await fetchModelCatalog<ModelInfo>();
        if (!cancelled) {
          setAllModels(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError({ message: err instanceof Error ? err.message : String(err) });
          setAllModels([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // Pre-compute tab counts once — shown as little badges on each tab
  // button. Cheaper than filtering the list 5 times.
  const tabCounts: Record<TabId, number> = {
    chat: 0,
    embedding: 0,
    image: 0,
    voice: 0,
  };
  for (const m of allModels) {
    tabCounts[tabForModel(m)]++;
  }

  // Models in the active tab, grouped by provider, so the page layout
  // stays consistent across tabs (provider header + model rows).
  const visibleModels = allModels.filter(
    (m) => tabForModel(m) === activeTab,
  );
  const providerGroups = groupModelsByProvider(visibleModels);

  const activeProviderCount = new Set(
    allModels
      .filter((m) => m.providerState !== "not_configured")
      .map((m) => m.provider),
  ).size;

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Page Header — matches /skills layout pattern */}
        <header>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              layers
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Models
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Configured LLM providers and model endpoints, grouped by capability.
          </p>
        </header>

      {/* Summary Bar — 3 glass cards */}
      <div className="flex gap-4 mb-8">
        <SummaryCard
          icon="layers"
          iconBg="bg-primary-container/20"
          iconColor="text-primary"
          label="Total Models"
          value={`${allModels.length} Models`}
        />
        <SummaryCard
          icon="hub"
          iconBg="bg-secondary-container/20"
          iconColor="text-secondary"
          label="Providers"
          value={`${activeProviderCount} Active`}
        />
        <SummaryCard
          icon="bolt"
          iconBg="bg-tertiary-container/20"
          iconColor="text-tertiary"
          label={`${TABS.find((t) => t.id === activeTab)?.label} Tab`}
          value={`${tabCounts[activeTab]} Models`}
        />
      </div>

      {/* Tabs */}
      <nav
        aria-label="Model categories"
        className="flex gap-1 mb-8 p-1 rounded-xl"
        style={glassStyle}
      >
        {TABS.map((tab) => {
          const isActive = tab.id === activeTab;
          const count = tabCounts[tab.id];
          return (
            <Link
              key={tab.id}
              href={`/models?tab=${tab.id}`}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-label uppercase tracking-wider transition-all ${
                // Active state mirrors the sidebar's active-link
                // pattern (bg-secondary-container/30 + text-secondary
                // green) so the "selected" affordance reads as one
                // shape across the app. (text-primary-fixed-dim,
                // #a7c8ff theme-invariant, would disappear on the
                // pale-azure light bg.)
                isActive
                  ? "bg-secondary-container/30 text-secondary border border-secondary/30"
                  : "text-on-surface-variant hover:bg-white/5 border border-transparent"
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">
                {tab.icon}
              </span>
              <span className="font-bold">{tab.label}</span>
              <span
                className={`ml-1 text-[10px] font-mono px-1.5 py-0.5 rounded-full ${
                  isActive
                    ? "bg-secondary/20 text-secondary"
                    : "bg-white/10 text-outline"
                }`}
              >
                {count}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Content — Error / Empty / Tab content */}
      {error ? (
        <div className="rounded-2xl p-8" style={glassStyle}>
          <h2 className="font-headline text-lg font-bold mb-2">
            Unable to load models
          </h2>
          <div className="flex flex-col gap-4 text-sm text-on-surface-variant sm:flex-row sm:items-center sm:justify-between">
            <p>{error.message}</p>
            <RetryButton />
          </div>
        </div>
      ) : visibleModels.length === 0 ? (
        <div
          className="rounded-2xl p-12 flex flex-col items-center gap-3 text-center"
          style={glassStyle}
        >
          <span className="material-symbols-outlined text-4xl text-on-surface-variant">
            {TABS.find((t) => t.id === activeTab)?.icon ?? "hub"}
          </span>
          <p className="text-base font-medium">
            No {TABS.find((t) => t.id === activeTab)?.label.toLowerCase()}{" "}
            models yet
          </p>
          <p className="max-w-xl text-sm text-on-surface-variant">
            {TABS.find((t) => t.id === activeTab)?.emptyHint}
          </p>
          <Link
            href="/settings/providers"
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold font-headline bg-primary-container text-on-primary-container hover:shadow-[0_0_15px_rgba(25,99,179,0.3)] transition-all"
          >
            <span className="material-symbols-outlined text-[16px]">
              settings
            </span>
            Open Provider Settings
          </Link>
        </div>
      ) : (
        <div className="space-y-12">
          {providerGroups
            .filter((g) => g.models.length > 0)
            .map((group) => (
              <section key={group.id}>
                {/* Provider Header with divider line */}
                <div className="flex items-center gap-4 mb-6">
                  <div className="h-10 w-10 bg-white/5 rounded-lg flex items-center justify-center border border-outline-variant/20">
                    <span className="material-symbols-outlined text-primary">
                      {group.icon}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-headline text-xl font-bold">
                      {group.label}
                    </h3>
                    <p
                      className="text-[11px] text-on-surface-variant truncate"
                      title={providerStatusLine(group.models)}
                    >
                      {providerStatusLine(group.models)}
                    </p>
                  </div>
                  <span className="h-px flex-1 bg-outline-variant/20" />
                  <span className="text-xs font-label uppercase tracking-widest text-outline">
                    {group.models.length}{" "}
                    {group.models.length === 1 ? "Model" : "Models"}
                  </span>
                </div>

                {/* Model Rows */}
                <div className="grid grid-cols-1 gap-4">
                  {group.models.map((model) => (
                    <ModelRow
                      key={model.ref ?? `${group.id}-${model.model}`}
                      model={model}
                      activeTab={activeTab}
                      isDefault={Boolean(model.isDefault)}
                      onSetDefault={async () => {
                        if (await setInstallDefaultModel(model.ref, model.displayName || model.model)) {
                          setReloadKey((k) => k + 1);
                        }
                      }}
                    />
                  ))}
                </div>
              </section>
            ))}
        </div>
      )}
      </div>
    </div>
  );
}

/* ── Glass style constant ─────────────────────── */
const glassStyle = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

/* ── Summary Card ─────────────────────────────── */
function SummaryCard({
  icon,
  iconBg,
  iconColor,
  label,
  value,
}: {
  icon: string;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
}) {
  return (
    <div
      className="flex-1 p-6 rounded-2xl flex items-center gap-4 hover:shadow-[0_0_20px_rgba(25,99,179,0.1)] transition-shadow"
      style={glassStyle}
    >
      <div
        className={`h-12 w-12 rounded-xl ${iconBg} flex items-center justify-center ${iconColor}`}
      >
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-outline">
          {label}
        </p>
        <p className="text-2xl font-bold font-headline">{value}</p>
      </div>
    </div>
  );
}

/* ── Model Row (vibrant glass card) ───────────── */

/** Availability badge: tone and label for every non-"available" state. */
const AVAILABILITY_BADGE: Record<string, { label: string; style: React.CSSProperties }> = {
  deprecated: {
    label: "Deprecated",
    style: { background: "rgba(255, 175, 0, 0.15)", color: "#ffc94f", border: "1px solid rgba(255, 175, 0, 0.3)" },
  },
  unverified: {
    label: "Unverified",
    style: { background: "rgba(150, 150, 150, 0.18)", color: "#b9b9b9", border: "1px solid rgba(150, 150, 150, 0.3)" },
  },
  unpriced: {
    label: "Unpriced",
    style: { background: "rgba(150, 150, 150, 0.18)", color: "#b9b9b9", border: "1px solid rgba(150, 150, 150, 0.3)" },
  },
  unavailable: {
    label: "Not visible to key",
    style: { background: "rgba(255, 90, 90, 0.15)", color: "#ff8f8f", border: "1px solid rgba(255, 90, 90, 0.3)" },
  },
  not_configured: {
    label: "Not configured",
    style: { background: "rgba(150, 150, 150, 0.18)", color: "#b9b9b9", border: "1px solid rgba(150, 150, 150, 0.3)" },
  },
  retired: {
    label: "Retired",
    style: { background: "rgba(255, 90, 90, 0.15)", color: "#ff8f8f", border: "1px solid rgba(255, 90, 90, 0.3)" },
  },
};

function ModelRow({
  model,
  activeTab,
  isDefault,
  onSetDefault,
}: {
  model: ModelInfo;
  activeTab: TabId;
  isDefault: boolean;
  onSetDefault: () => void;
}) {
  const href = `/models/${encodeURIComponent(model.model)}?provider=${encodeURIComponent(model.provider)}`;
  const patterns = model.interactionPatterns ?? [];

  // Determine the left-side icon by model kind — gives each tab a
  // visually distinct row style without needing per-tab components.
  const rowIcon = iconForKind(model.kind, model.supportsThinking);

  // A model whose provider is not configured stays listed (the detail page
  // shows what it would cost and what it can do) but reads as inactive.
  const inactive = model.availability === "not_configured";
  const badge = AVAILABILITY_BADGE[model.availability];
  const price = formatPriceLine(model);

  return (
    <Link
      href={href}
      className={`block p-5 rounded-xl flex items-center justify-between group cursor-pointer transition-all hover:shadow-[0_0_20px_rgba(25,99,179,0.1)] ${
        inactive ? "opacity-60" : ""
      }`}
      style={{
        background: "var(--glass-bg)",
        backdropFilter: "blur(12px)",
        border: "0.5px solid var(--glass-border)",
      }}
      title={model.reason ?? undefined}
    >
      {/* Left: Icon + Name */}
      <div className="flex items-center gap-6 flex-1 min-w-0">
        <div className="w-12 h-12 rounded-lg bg-surface-container flex items-center justify-center relative shrink-0">
          <span className="material-symbols-outlined text-primary">
            {rowIcon}
          </span>
          <div
            className={
              inactive || !model.selectable
                ? "absolute -top-1 -right-1 w-3 h-3 bg-outline rounded-full"
                : "absolute -top-1 -right-1 w-3 h-3 bg-secondary rounded-full shadow-[0_0_8px_#7bdc7b]"
            }
          />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="font-headline font-bold text-lg text-on-surface truncate">
              {model.displayName || model.model}
            </h4>
            {isDefault && (
              <span
                className="px-2 py-0.5 rounded-md bg-primary-container text-[10px] font-bold uppercase tracking-wider text-on-primary-container"
                title={defaultSourceHint(model.defaultSource)}
              >
                {model.defaultSource === "derived" ? "Default (derived)" : "Default"}
              </span>
            )}
            {badge && (
              <span
                className="px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider"
                style={badge.style}
                title={model.reason ?? undefined}
              >
                {badge.label}
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
                  title={`Launch stage: ${model.launchStage}`}
                >
                  {model.launchStage.replace(/_/g, " ")}
                </span>
              )}
          </div>
          <code className="text-xs text-outline font-mono">{model.ref}</code>
        </div>
      </div>

      {/* Center: Badges + Metrics */}
      <div className="hidden md:flex items-center gap-8 text-sm text-on-surface-variant flex-[1.5] justify-center">
        {/* Interaction pattern badges */}
        {patterns.length > 0 && (
          <div className="flex gap-1.5">
            {patterns.map((pattern) => {
              const patternBadge = PATTERN_BADGE[pattern];
              if (!patternBadge) return null;
              return (
                <span
                  key={pattern}
                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${patternBadge.color}`}
                >
                  {patternBadge.label}
                </span>
              );
            })}
          </div>
        )}

        {/* Capability icons — only show for the chat tab; other
            tabs (embedding, image, voice) have different capability
            dimensions that we haven't modeled yet. */}
        {activeTab === "chat" && (
          <>
            {model.supportsThinking && (
              <div
                className="flex items-center gap-1.5"
                title="Supports extended thinking"
              >
                <span className="material-symbols-outlined text-[16px] text-primary">
                  psychology
                </span>
                <span className="text-xs">Thinking</span>
              </div>
            )}
            {model.supportsTools && (
              <div
                className="flex items-center gap-1.5"
                title="Supports tool calling"
              >
                <span className="material-symbols-outlined text-[16px] text-tertiary">
                  build
                </span>
                <span className="text-xs">Tools</span>
              </div>
            )}
          </>
        )}

        {/* Price per million input / output tokens (chat only) */}
        {activeTab === "chat" && (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-outline">
              $ / M in / out
            </div>
            <span className="font-bold text-on-surface">{price ?? "—"}</span>
          </div>
        )}

        {/* Context window (only meaningful for chat/embedding) */}
        {activeTab !== "image" && activeTab !== "voice" && (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-outline">
              Context
            </div>
            <span className="font-bold text-on-surface">
              {formatContextWindow(model.contextWindow)}
            </span>
          </div>
        )}
      </div>

      {/* The default can be set from the list. The row is a link, so the
          click must not navigate. A model that is already the install's own
          default has nothing to set; a derived default can be pinned. */}
      {(model.kind ?? "chat") === "chat" &&
        model.selectable &&
        !(isDefault && model.defaultSource === "default") && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onSetDefault();
            }}
            className="ml-4 shrink-0 px-3 py-1.5 rounded-lg text-[11px] font-bold font-label uppercase tracking-wider text-primary border border-primary/30 hover:bg-primary/10 transition-colors"
            aria-label={`Set ${model.displayName || model.model} as the default model`}
          >
            Set as default
          </button>
        )}

      <span className="material-symbols-outlined text-outline group-hover:text-primary transition-colors ml-4 shrink-0">
        arrow_forward
      </span>
    </Link>
  );
}

function iconForKind(kind: ModelKind | undefined, thinking: boolean): string {
  switch (kind) {
    case "embedding":
      return "scatter_plot";
    case "image":
      return "image";
    case "voice":
      return "graphic_eq";
    default:
      return thinking ? "psychology" : "auto_awesome";
  }
}

/* ── Helper functions ─────────────────────────── */

function groupModelsByProvider(models: ModelInfo[]): ProviderGroup[] {
  const modelMap = new Map<string, ModelInfo[]>();

  for (const model of models) {
    const providerId = normalizeProvider(model.provider);
    const group = modelMap.get(providerId) ?? [];
    group.push(model);
    modelMap.set(providerId, group);
  }

  const orderedGroups: ProviderGroup[] = KNOWN_PROVIDERS.map((provider) => {
    const groupedModels = sortModels(modelMap.get(provider.id) ?? []);
    modelMap.delete(provider.id);

    return {
      id: provider.id,
      label: provider.label,
      icon: provider.icon,
      models: groupedModels,
      status: groupedModels.length > 0 ? "connected" : "disconnected",
    };
  });

  const extraGroups = Array.from(modelMap.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(
      ([providerId, groupedModels]) =>
        ({
          id: providerId,
          label: formatProviderLabel(providerId),
          icon: "hub",
          models: sortModels(groupedModels),
          status: groupedModels.length > 0 ? "connected" : "disconnected",
        }) satisfies ProviderGroup,
    );

  return [...orderedGroups, ...extraGroups];
}

/** One line on where this provider's list came from and how fresh it is. */
function providerStatusLine(models: ModelInfo[]): string {
  const first = models[0];
  if (!first) return "";
  const when = models
    .map((m) => m.liveSeenAt)
    .filter((t): t is string => Boolean(t))
    .sort()
    .pop();
  const time = when ? new Date(when).toLocaleTimeString() : "";
  switch (first.providerState) {
    case "live":
      return `Live list fetched ${time}`;
    case "stale":
      return `Showing the list fetched ${time}. The provider could not be reached since${
        first.refreshError ? `: ${first.refreshError}` : "."
      }`;
    case "offline":
      return `Showing the built-in table. The provider could not be reached${
        first.refreshError ? `: ${first.refreshError}` : "."
      }`;
    case "unchecked":
      return "Built-in table. Use Verify on a model to confirm it is enabled.";
    case "not_configured":
      return "Not configured. Add credentials on the Providers page.";
    default:
      return "";
  }
}

function sortModels(models: ModelInfo[]): ModelInfo[] {
  // GA first, then lexicographic descending so newer model versions
  // (gemini-3.x > gemini-2.5.x > gemini-2.0.x) sort to the top.
  return [...models].sort((left, right) => {
    const leftGA = (left.launchStage ?? "GA") === "GA";
    const rightGA = (right.launchStage ?? "GA") === "GA";
    if (leftGA !== rightGA) return leftGA ? -1 : 1;
    return right.model.localeCompare(left.model);
  });
}

function normalizeProvider(provider: string): string {
  return provider.trim().toLowerCase();
}

function formatProviderLabel(providerId: string): string {
  return providerId
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
