"use client";

/**
 * Detections inventory page.
 *
 * Surfaces the MCP's /api/v1/detections inventory (declared in
 * bundles/spark/mcp/src/api/detections.py) to the
 * operator. Two views:
 *
 *   * Rules tab — table of detection rules with aggregated fire
 *     counts (last 24h / 7d / 30d / total) + technique-id chips
 *   * Coverage tab — aggregated by MITRE T-code, showing how many
 *     rules + fires hit each technique
 *
 * Gives operators a non-chat path to browse the detection
 * inventory (the chat-driven detections_list tool is the other
 * path).
 *
 * Data sources:
 *   /api/agent/detections                       → rules tab
 *   /api/agent/detections/coverage/techniques   → coverage tab
 *
 * Both endpoints are bearer-auth proxies to the MCP. No client-side
 * auth: the route handlers attach the MCP_TOKEN server-side.
 */

import { useEffect, useState, useCallback } from "react";

interface Rule {
  rule_id: string;
  rule_name?: string | null;
  severity?: string | null;
  detection_method?: string | null;
  technique_ids?: string[];
  fires_total: number;
  fires_24h: number;
  fires_7d: number;
  fires_30d: number;
  first_fire_at?: string;
  last_fire_at?: string;
}

interface TechniqueCoverage {
  technique_id: string;
  rules_count: number;
  fires_24h: number;
  fires_7d: number;
  fires_30d: number;
  last_fire_at?: string;
}

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

type Tab = "rules" | "coverage";

export default function DetectionsPage() {
  const [tab, setTab] = useState<Tab>("rules");
  const [rules, setRules] = useState<Rule[]>([]);
  const [coverage, setCoverage] = useState<TechniqueCoverage[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [techniqueFilter, setTechniqueFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (severityFilter) qs.set("severity", severityFilter);
      if (techniqueFilter) qs.set("technique", techniqueFilter);
      qs.set("limit", "500");
      const [rulesRes, coverageRes] = await Promise.all([
        fetch(`/api/agent/detections?${qs.toString()}`, { cache: "no-store" }),
        fetch(`/api/agent/detections/coverage/techniques`, { cache: "no-store" }),
      ]);
      if (!rulesRes.ok) throw new Error(`detections fetch ${rulesRes.status}`);
      const rulesBody = await rulesRes.json();
      setRules(rulesBody.rules ?? []);
      if (coverageRes.ok) {
        const coverageBody = await coverageRes.json();
        // MCP returns { techniques: { <T-code>: {rules_count, fires_*, last_fire_at} } }
        // (a dict keyed by T-code). Transform to a list for table rendering.
        // Each value already has technique_id baked in by the MCP — see
        // bundles/spark/mcp/src/usecase/detection_inventory.py::technique_coverage().
        const techDict = (coverageBody.techniques ?? {}) as Record<string, TechniqueCoverage>;
        const techList = Object.values(techDict).sort(
          (a, b) => (b.fires_30d ?? 0) - (a.fires_30d ?? 0),
        );
        setCoverage(techList);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }, [severityFilter, techniqueFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const severityBadge = (s?: string | null) => {
    if (!s) return null;
    const color = (
      {
        critical: "#ff3344",
        high: "#ff8800",
        medium: "#ffcc00",
        low: "#66cc66",
      } as Record<string, string>
    )[s.toLowerCase()] ?? "#888";
    return (
      <span
        style={{
          background: color,
          color: "#000",
          padding: "2px 8px",
          borderRadius: 4,
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
        }}
      >
        {s}
      </span>
    );
  };

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header — matches /skills layout pattern */}
        <header>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              radar
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Detection inventory
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Detection rules + fire history aggregated from XSIAM / SIEM. Ask Phantom to run the coverage cycle (<code className="font-mono">coverage_cycle_run</code>), or POST to <code className="font-mono">/api/agent/detections/sync</code>.
          </p>
        </header>

      {/* Tab switcher */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, borderBottom: "1px solid var(--glass-border)" }}>
        {(["rules", "coverage"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              padding: "10px 20px",
              background: "transparent",
              border: "none",
              borderBottom: tab === t ? "2px solid var(--primary)" : "2px solid transparent",
              color: tab === t ? "var(--text-primary)" : "var(--text-secondary)",
              fontWeight: tab === t ? 600 : 400,
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Filters */}
      {tab === "rules" && (
        <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
          <input
            type="text"
            placeholder="Severity (critical / high / medium / low)"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value.trim().toLowerCase())}
            style={{
              padding: "8px 12px",
              background: "var(--bg-secondary)",
              border: "1px solid var(--glass-border)",
              borderRadius: 6,
              color: "var(--text-primary)",
              width: 280,
            }}
          />
          <input
            type="text"
            placeholder="MITRE T-code (e.g. T1059.001)"
            value={techniqueFilter}
            onChange={(e) => setTechniqueFilter(e.target.value.trim())}
            style={{
              padding: "8px 12px",
              background: "var(--bg-secondary)",
              border: "1px solid var(--glass-border)",
              borderRadius: 6,
              color: "var(--text-primary)",
              width: 240,
            }}
          />
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            style={{
              padding: "8px 16px",
              background: "var(--primary)",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: loading ? "wait" : "pointer",
              fontWeight: 500,
            }}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
          <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            {rules.length} rule{rules.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {error && (
        <div
          style={{
            ...glassStyle,
            padding: 16,
            borderRadius: 8,
            color: "#ff3344",
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {/* Rules tab */}
      {tab === "rules" && (
        <div style={{ ...glassStyle, borderRadius: 8, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-secondary)" }}>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Rule</th>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Severity</th>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Method</th>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Techniques</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>24h</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>7d</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>30d</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>Total</th>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Last fire</th>
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={9}
                    style={{
                      padding: 48,
                      textAlign: "center",
                      color: "var(--text-secondary)",
                    }}
                  >
                    No detection rules yet. Ask Phantom to run the coverage
                    cycle (<code>coverage_cycle_run</code> — fetches XSIAM
                    issues, syncs the inventory, takes a coverage snapshot),
                    or POST to <code>/api/agent/detections/sync</code>{" "}
                    directly. Add it as a recurring job via{" "}
                    <code>/jobs/new</code> for automatic daily syncing —
                    it isn&apos;t seeded by default.
                  </td>
                </tr>
              )}
              {rules.map((r) => (
                <tr key={r.rule_id} style={{ borderTop: "1px solid var(--glass-border)" }}>
                  <td style={{ padding: 12 }}>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>
                      {r.rule_name || r.rule_id}
                    </div>
                    {r.rule_name && (
                      <div style={{ fontSize: 11, color: "var(--text-secondary)", fontFamily: "monospace" }}>
                        {r.rule_id}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: 12 }}>{severityBadge(r.severity)}</td>
                  <td style={{ padding: 12, fontSize: 13 }}>{r.detection_method || "—"}</td>
                  <td style={{ padding: 12 }}>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {(r.technique_ids ?? []).map((t) => (
                        <span
                          key={t}
                          style={{
                            background: "var(--bg-secondary)",
                            padding: "2px 6px",
                            borderRadius: 3,
                            fontSize: 11,
                            fontFamily: "monospace",
                          }}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{r.fires_24h}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{r.fires_7d}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{r.fires_30d}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace", fontWeight: 600 }}>{r.fires_total}</td>
                  <td style={{ padding: 12, fontSize: 12, color: "var(--text-secondary)" }}>
                    {r.last_fire_at ? new Date(r.last_fire_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Coverage tab */}
      {tab === "coverage" && (
        <div style={{ ...glassStyle, borderRadius: 8, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-secondary)" }}>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>MITRE technique</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>Rules</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>24h</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>7d</th>
                <th style={{ padding: 12, textAlign: "right", fontSize: 12, fontWeight: 600 }}>30d</th>
                <th style={{ padding: 12, textAlign: "left", fontSize: 12, fontWeight: 600 }}>Last fire</th>
              </tr>
            </thead>
            <tbody>
              {coverage.length === 0 && !loading && (
                <tr>
                  <td
                    colSpan={6}
                    style={{
                      padding: 48,
                      textAlign: "center",
                      color: "var(--text-secondary)",
                    }}
                  >
                    No coverage data yet. Sync the detection inventory first.
                  </td>
                </tr>
              )}
              {coverage.map((c) => (
                <tr key={c.technique_id} style={{ borderTop: "1px solid var(--glass-border)" }}>
                  <td style={{ padding: 12, fontFamily: "monospace", fontWeight: 500 }}>{c.technique_id}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{c.rules_count}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{c.fires_24h ?? 0}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace" }}>{c.fires_7d ?? 0}</td>
                  <td style={{ padding: 12, textAlign: "right", fontFamily: "monospace", fontWeight: 600 }}>{c.fires_30d ?? 0}</td>
                  <td style={{ padding: 12, fontSize: 12, color: "var(--text-secondary)" }}>
                    {c.last_fire_at ? new Date(c.last_fire_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </div>
  );
}
