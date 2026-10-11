import type { ReactNode } from "react";

/**
 * Observability shell — phantom version.
 *
 * Spark's observability tab bar + Grafana link + datasource indicators
 * are removed here. Phantom is self-contained: there's no Grafana,
 * no Prometheus server, no Tempo, no Loki sitting alongside the
 * agent. The MCP exposes /api/v1/metrics, /api/v1/audit, and
 * (incrementally) trace + log surfaces directly. Each subpage under
 * /observability/* renders against those phantom-internal endpoints.
 *
 * Sidebar nav now lists the subpages individually (Services /
 * Metrics / Traces / Logs / Events / Pipeline) so navigation goes
 * through the global sidebar, not a section-local tab bar.
 */
export default function ObservabilityLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <div className="min-h-screen">{children}</div>;
}

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Observability · Phantom",
};
