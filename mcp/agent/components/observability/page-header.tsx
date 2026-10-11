import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * Datasource health status used by the centered indicator chips in
 * the Observability page header. Today these are hardcoded to "ok"
 * for every page — we'll flip them to derive from real Grafana
 * datasource health checks when we wire the lib/observability clients.
 */
export type DatasourceHealth = "ok" | "degraded" | "down";

export type ObservabilityPageHeaderProps = {
  /** Material Symbols icon name displayed next to the page title. */
  icon: string;
  /** Page title (e.g. "Overview", "Traces"). */
  title: string;
  /** One-line subtitle shown below the title. */
  subtitle?: string;
  /** Current breadcrumb path segment — always prefixed with "Observability". */
  breadcrumb: string;
  /**
   * Per-datasource health. Keys are fixed: prometheus, loki, tempo.
   * Defaults to all "ok" when omitted so pages that don't know their
   * own health status can still render.
   */
  datasources?: {
    prometheus?: DatasourceHealth;
    loki?: DatasourceHealth;
    tempo?: DatasourceHealth;
  };
  /**
   * Currently-selected time range chip. URL state lives on the
   * parent page; the header only renders the visual highlight.
   */
  activeRange?: "5m" | "15m" | "1h" | "6h" | "24h";
};

const DEFAULT_DATASOURCES: Required<
  NonNullable<ObservabilityPageHeaderProps["datasources"]>
> = {
  prometheus: "ok",
  loki: "ok",
  tempo: "ok",
};

const RANGE_CHIPS: Array<"5m" | "15m" | "1h" | "6h" | "24h"> = [
  "5m",
  "15m",
  "1h",
  "6h",
  "24h",
];

/**
 * Shared header for every Observability sub-page. Provides:
 *
 *   • Breadcrumb + page title + icon on the left
 *   • Three datasource health chips in the center (Prometheus / Loki / Tempo)
 *   • Time-range chip group + "Open in Grafana" button on the right
 *
 * The whole thing is a server component — no interactivity yet because
 * the time-range and refresh controls will be wired up later when we
 * introduce a URL-state hook. For now every visitor gets the defaults.
 *
 * Consumers pass `icon`, `title`, `subtitle`, and `breadcrumb`; the rest
 * have sensible defaults so a minimal caller looks like:
 *
 *   <ObservabilityPageHeader
 *     icon="timeline"
 *     title="Traces"
 *     breadcrumb="Traces"
 *     subtitle="Distributed trace explorer (Tempo)"
 *   />
 */
export function ObservabilityPageHeader({
  icon,
  title,
  subtitle,
  breadcrumb,
  datasources,
  activeRange = "1h",
}: ObservabilityPageHeaderProps) {
  const ds = { ...DEFAULT_DATASOURCES, ...(datasources ?? {}) };

  return (
    <header className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 mb-8">
      {/* Left: breadcrumb + icon + title + subtitle */}
      <div className="space-y-1">
        <nav
          aria-label="Breadcrumb"
          className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-on-surface-variant/70"
        >
          <Link
            className="hover:text-on-surface transition-colors"
            href="/observability"
          >
            Observability
          </Link>
          {breadcrumb !== "Overview" && (
            <>
              <span aria-hidden="true">›</span>
              <span className="text-on-surface">{breadcrumb}</span>
            </>
          )}
        </nav>
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-3xl text-primary"
          >
            {icon}
          </span>
          <h1 className="font-headline text-4xl font-bold tracking-tight text-on-surface">
            {title}
          </h1>
        </div>
        {subtitle && (
          <p className="text-sm font-light text-on-surface-variant ml-11">
            {subtitle}
          </p>
        )}
      </div>

      {/* Right: datasource health + time range + Grafana link */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Datasource health chips */}
        <div
          aria-label="Datasource health"
          className="flex items-center gap-2 px-3 py-2 bg-surface-container-low rounded-lg border border-white/5"
        >
          <DatasourceChip label="Prometheus" status={ds.prometheus} />
          <DatasourceChip label="Loki" status={ds.loki} />
          <DatasourceChip label="Tempo" status={ds.tempo} />
        </div>

        {/* Time range chip group */}
        <div
          aria-label="Time range"
          className="flex bg-surface-container-low p-1 rounded-lg border border-white/5"
        >
          {RANGE_CHIPS.map((range) => (
            <button
              key={range}
              type="button"
              className={cn(
                "px-3 py-1 text-[10px] font-mono font-bold uppercase transition-colors rounded-md",
                range === activeRange
                  ? "bg-primary-container text-on-primary-container shadow-lg"
                  : "text-on-surface-variant hover:text-on-surface",
              )}
            >
              {range}
            </button>
          ))}
        </div>

        {/* Open in Grafana */}
        <a
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary-container/20 hover:bg-primary-container/30 text-primary-fixed-dim font-medium text-sm border border-primary-container/30 transition-colors"
          href="https://localhost:3000/grafana"
          rel="noopener noreferrer"
          target="_blank"
        >
          Open in Grafana
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-sm"
          >
            open_in_new
          </span>
        </a>
      </div>
    </header>
  );
}

/**
 * Single datasource health chip — a tiny colored dot + label.
 * Kept private because it's meaningless outside the header context.
 */
function DatasourceChip({
  label,
  status,
}: {
  label: string;
  status: DatasourceHealth;
}) {
  const dotClass =
    status === "ok"
      ? "bg-[#7bdc7b] shadow-[0_0_6px_rgba(123,220,123,0.5)]"
      : status === "degraded"
        ? "bg-tertiary"
        : "bg-error animate-pulse";

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 rounded-full">
      <span
        aria-label={`${label} ${status}`}
        className={cn("w-1.5 h-1.5 rounded-full", dotClass)}
      />
      <span className="font-mono text-[10px] text-on-surface-variant">
        {label}
      </span>
    </div>
  );
}
