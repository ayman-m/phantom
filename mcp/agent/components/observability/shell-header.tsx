import { cn } from "@/lib/utils";
import { promTargets } from "@/lib/observability/prometheus";
import { lokiReady } from "@/lib/observability/loki";
import { tempoReady } from "@/lib/observability/tempo";

/**
 * Shared header for the Observability shell.
 *
 * This header is rendered ONCE by the shared layout (not per sub-page
 * with its own title/icon/subtitle) and stays constant
 * across all 6 tabs. The tab bar below it tells the user which view
 * they are currently on — this header only communicates "you are in
 * the Observability section of Spark".
 *
 * Contents, left → right:
 *   • Title: `Observability`
 *   • Subtitle: `Platform-wide telemetry — metrics, logs, events, traces`
 *   • Live datasource health dots: Prometheus · Loki · Tempo
 *   • Time range chip group: 5m / 15m / 1h / 6h / 24h
 *   • "Open in Grafana" link
 *
 * The datasource dots now probe the live LGTM backends on every render
 * (server component, `force-dynamic`). If any probe fails, the dot goes
 * red and the shell header is the single source of truth for "is the
 * telemetry pipeline actually working".
 *
 * The time-range chips are still static placeholders — when real
 * range-selection lands, they become a client component backed by URL
 * state that every tab re-reads via `useSearchParams`.
 */

type DatasourceHealth = "ok" | "degraded" | "down";

type ObservabilityShellHeaderProps = {
  activeRange?: "5m" | "15m" | "1h" | "6h" | "24h";
};

const RANGE_CHIPS: Array<"5m" | "15m" | "1h" | "6h" | "24h"> = [
  "5m",
  "15m",
  "1h",
  "6h",
  "24h",
];

async function probeDatasourceHealth(): Promise<{
  prometheus: DatasourceHealth;
  loki: DatasourceHealth;
  tempo: DatasourceHealth;
}> {
  // Run all three probes in parallel so the header render cost is
  // dominated by the slowest backend, not the sum. Each probe has its
  // own short timeout inside the client.
  const [promResult, lokiOk, tempoOk] = await Promise.all([
    promTargets(),
    lokiReady(),
    tempoReady(),
  ]);

  // Prometheus: use its own /api/v1/targets response to grade itself.
  // If the request succeeded at all, Prometheus is "ok". Degraded
  // (yellow) is reserved for "reachable but some targets are down" so
  // the operator sees a warning without a full red alarm.
  let prometheus: DatasourceHealth;
  if (!promResult.ok) {
    prometheus = "down";
  } else {
    const total = promResult.data.length;
    const downCount = promResult.data.filter((t) => t.health === "down").length;
    if (total === 0 || downCount === total) {
      prometheus = "down";
    } else if (downCount > 0) {
      prometheus = "degraded";
    } else {
      prometheus = "ok";
    }
  }

  return {
    prometheus,
    loki: lokiOk ? "ok" : "down",
    tempo: tempoOk ? "ok" : "down",
  };
}

export async function ObservabilityShellHeader({
  activeRange = "1h",
}: ObservabilityShellHeaderProps = {}) {
  const ds = await probeDatasourceHealth();

  return (
    <header className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 mb-6">
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-4xl text-primary"
          >
            query_stats
          </span>
          <h1 className="font-headline text-4xl font-bold tracking-tight text-on-surface">
            Observability
          </h1>
        </div>
        <p className="text-sm font-light text-on-surface-variant ml-[60px]">
          Platform-wide telemetry — metrics, logs, events, and traces across
          every Spark service
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
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
