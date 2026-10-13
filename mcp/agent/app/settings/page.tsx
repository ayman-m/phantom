"use client";

import { useCallback, useEffect, useState } from "react";
import {
  languageCounts,
  serviceHealthRow,
  type HealthPayload,
  type ServiceHealth,
} from "@/lib/service-health";

// ── Types ────────────────────────────────────────────────────────────────────

type PanelView = null | string; // service name or null

interface ServiceDef {
  name: string;
  icon: string;
  language: string; // free-form for phantom (e.g. "Python 3.12 / FastAPI")
  description: string;
  layer: string;
  port: string;
  healthEndpoint: string;
  /** Probe id in GET /api/agent/health; null = no probe of its own. */
  probeId: string | null;
  envVars: { key: string; value: string; masked?: boolean }[];
  dependencies: { name: string; icon: string }[];
}

// ── Constants ────────────────────────────────────────────────────────────────

const glassPanel: React.CSSProperties = {
  background: "var(--glass-bg)",
  backdropFilter: "blur(20px)",
  border: "1px solid var(--glass-border)",
};

const slidePanel: React.CSSProperties = {
  background: "var(--glass-bg-elev)",
  backdropFilter: "blur(16px)",
  borderLeft: "0.5px solid var(--glass-border)",
};

interface LayerGroup {
  name: string;
  color: string;
  textColor: string;
  services: ServiceDef[];
}

// ── Phantom service inventory ──────────────────────────────────────────────
//
// Phantom is a 5-service Docker Compose stack — much smaller than the Spark
// workspace. The layer groupings here track the compose topology:
//   Cognitive    → phantom-agent (Next.js + embedded MCP)
//   Telemetry    → xlog (log generation)
//   Adversary    → caldera (MITRE adversary emulation)
//   Storage      → sqlite (in-process, embedded in MCP)
// Each service's config is derived from real env variables (visible in
// compose.yml); its status comes from the server-side probes behind
// GET /api/agent/health. The embedded sqlite stores have no probe of their own
// and report the phantom-mcp probe, because they live inside that process.
const LAYER_GROUPS: LayerGroup[] = [
  {
    name: "Cognitive Layer",
    color: "#1f7bff",
    textColor: "text-primary-fixed-dim",
    services: [
      {
        name: "phantom-agent", icon: "smart_toy", language: "TypeScript / Next.js 15",
        description: "Operator UI + chat orchestrator. Routes prompts through the configured model provider (Gemini, Claude or OpenAI), fans tool calls into the embedded MCP.",
        layer: "Cognitive", port: ":3000", healthEndpoint: "/api/auth/status", probeId: "phantom-agent",
        envVars: [
          { key: "MCP_URL", value: "http://phantom-mcp:8080/api/v1/stream/mcp" },
          { key: "MCP_TOKEN", value: "(container env)", masked: true },
          { key: "GEMINI_API_KEY", value: "(operator-supplied)", masked: true },
          { key: "GOOGLE_APPLICATION_CREDENTIALS", value: "(Vertex SA JSON)", masked: true },
          { key: "UI_USER", value: "phantom" },
          { key: "UI_PASSWORD", value: "(operator-supplied)", masked: true },
        ],
        dependencies: [
          { name: "phantom-mcp (embedded)", icon: "extension" },
        ],
      },
      {
        name: "phantom-mcp (embedded)", icon: "extension", language: "Python 3.12 / FastMCP",
        description: "MCP server hosting ~80 tools across xlog/caldera/xsiam. Sqlite-backed audit, sessions, secrets, settings.",
        layer: "Cognitive", port: ":8080", healthEndpoint: "/ping/", probeId: "phantom-mcp",
        envVars: [
          { key: "MCP_TRANSPORT", value: "streamable-http" },
          { key: "MCP_PATH", value: "/api/v1/stream/mcp" },
          { key: "MCP_TOKEN", value: "(generated at boot if absent)", masked: true },
          { key: "PHANTOM_SECRET_KEK", value: "(operator-supplied for encryption-at-rest)", masked: true },
        ],
        dependencies: [
          { name: "xlog", icon: "data_object" },
          { name: "caldera", icon: "shield" },
        ],
      },
    ],
  },
  {
    name: "Telemetry Layer",
    color: "#00f5ff",
    textColor: "text-[#00f5ff]",
    services: [
      {
        name: "xlog", icon: "data_object", language: "Python 3.12 / FastAPI",
        description: "Synthetic log generation engine. GraphQL API; emits SYSLOG/CEF/JSON to webhooks, XSIAM PAPI, or files.",
        layer: "Telemetry", port: ":8000 (host :8999)", healthEndpoint: "/health", probeId: "xlog-api",
        envVars: [
          { key: "XLOG_API_KEY", value: "(operator-supplied bearer)", masked: true },
          { key: "WORKERS_NUMBER", value: "4" },
          { key: "WEBHOOK_ENDPOINT", value: "(downstream sink)" },
          { key: "WEBHOOK_KEY", value: "(downstream auth)", masked: true },
        ],
        dependencies: [],
      },
    ],
  },
  {
    name: "Adversary Emulation Layer",
    color: "#ff5f8a",
    textColor: "text-[#ff5f8a]",
    services: [
      {
        name: "caldera", icon: "shield", language: "Python 3 / aiohttp",
        description: "MITRE Caldera 5.3 — adversary emulation server. v2 REST API, abilities + adversaries + operations.",
        layer: "Adversary", port: ":8888 (host), :8443 (TLS)", healthEndpoint: "/", probeId: "caldera",
        envVars: [
          { key: "CALDERA_API_KEY", value: "(operator-supplied)", masked: true },
          { key: "CALDERA_RED_USER", value: "red" },
          { key: "CALDERA_RED_PASSWORD", value: "(operator-supplied)", masked: true },
        ],
        dependencies: [],
      },
    ],
  },
  {
    name: "Storage Layer",
    color: "#6a7cff",
    textColor: "text-[#6a7cff]",
    services: [
      {
        name: "sqlite (embedded)", icon: "database", language: "C / sqlite3",
        description: "In-process sqlite databases under /app/data/ for audit, sessions, memories, jobs, notifications, api_keys, settings, instances. No separate process — lives inside phantom-mcp.",
        layer: "Storage", port: "(in-process)", healthEndpoint: "n/a", probeId: "phantom-mcp",
        envVars: [
          { key: "PHANTOM_DATA_ROOT", value: "/app/data" },
          { key: "PHANTOM_SECRET_KEK", value: "(AES-256-GCM KEK for secret encryption-at-rest)", masked: true },
        ],
        dependencies: [],
      },
    ],
  },
];

const ALL_SERVICES = LAYER_GROUPS.flatMap((g) => g.services);

const LANG_BADGE: Record<string, { bg: string; text: string; border: string }> = {
  Go: { bg: "bg-primary-container/20", text: "text-primary", border: "border-primary/20" },
  Python: { bg: "bg-secondary-container/20", text: "text-secondary", border: "border-secondary/20" },
  TypeScript: { bg: "bg-[#00AADE]/20", text: "text-[#00AADE]", border: "border-[#00AADE]/20" },
  C: { bg: "bg-tertiary/15", text: "text-tertiary", border: "border-tertiary/30" },
};

// Service language strings are formatted ("Python 3.12 / FastAPI",
// "TypeScript / Next.js 15") — the LANG_BADGE map is keyed on the
// bare language root. Extract the first whitespace-delimited token
// for the lookup. Falls back to a neutral grey badge when the token
// isn't in the map (so a new language doesn't blow up the page —
// previous behavior was an undefined LANG_BADGE[svc.language] which
// crashed on `${badge.bg}` in the JSX below; client-side exception
// when navigating to /settings).
const FALLBACK_LANG_BADGE = {
  bg: "bg-white/5",
  text: "text-on-surface-variant",
  border: "border-white/10",
};
function badgeForLanguage(language: string) {
  const root = language.trim().split(/\s+/)[0] ?? "";
  return LANG_BADGE[root] ?? FALLBACK_LANG_BADGE;
}

// ── Page Component ───────────────────────────────────────────────────────────

export default function ServicesSettingsPage() {
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedService, setSelectedService] = useState<PanelView>(null);
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set());

  // ── Data fetching ────────────────────────────────────────────────────────

  // The health route answers 503 with a full body when every probe fails, so
  // the body is read whatever the status. A network failure leaves every
  // service "unknown" rather than inventing a state.
  const loadStatuses = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/agent/health", { cache: "no-store" });
      setHealth((await res.json()) as HealthPayload);
    } catch {
      setHealth(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadStatuses();
  }, [loadStatuses]);

  // ── Helpers ──────────────────────────────────────────────────────────────

  function rowFor(svc: ServiceDef) {
    return serviceHealthRow(health, svc.probeId);
  }

  function getStatus(name: string): ServiceHealth {
    const svc = ALL_SERVICES.find((s) => s.name === name);
    return svc ? rowFor(svc).status : "unknown";
  }

  function statusDot(status: string) {
    if (status === "healthy") return { dot: "bg-secondary", label: "Healthy", labelColor: "text-secondary", pulse: true };
    if (status === "degraded") return { dot: "bg-tertiary", label: "Degraded", labelColor: "text-tertiary", pulse: false };
    if (status === "unhealthy") return { dot: "bg-error", label: "Down", labelColor: "text-error", pulse: false };
    return { dot: "bg-outline", label: "Unknown", labelColor: "text-outline", pulse: false };
  }

  function toggleSecret(key: string) {
    setVisibleSecrets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const selectedDef = ALL_SERVICES.find((s) => s.name === selectedService);
  const healthyCount = ALL_SERVICES.filter((s) => getStatus(s.name) === "healthy").length;
  const languages = languageCounts(ALL_SERVICES.map((s) => s.language));

  // ── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="h-screen overflow-y-auto custom-scrollbar">
        <div className="max-w-[1400px] mx-auto px-8 py-10">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-48 bg-white/5 rounded" />
            <div className="h-64 bg-white/5 rounded-xl" />
          </div>
        </div>
      </main>
    );
  }

  return (
    <>
      <main className="h-screen overflow-y-auto custom-scrollbar">
        <div className="max-w-[1400px] mx-auto px-8 py-10 space-y-12">
          {/* Page Header — jobs-style (icon + title + subtitle). */}
          <header>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                tune
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Services
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Backend microservice inventory and health.
            </p>
          </header>

          {/* Layer Groups */}
          {LAYER_GROUPS.map((group) => (
            <section key={group.name} className="space-y-6">
              <div className="flex items-center gap-3">
                <div
                  className="h-1 w-12 rounded-full"
                  style={{ backgroundColor: group.color }}
                />
                <h3
                  className={`font-headline text-xs font-bold uppercase tracking-[0.2em] ${group.textColor}`}
                >
                  {group.name}
                </h3>
              </div>

              <div className={`grid gap-3 ${
                group.name === "Connector Layer" ? "md:grid-cols-2" : ""
              }`}>
                {group.services.map((svc) => {
                  const st = statusDot(getStatus(svc.name));
                  const badge = badgeForLanguage(svc.language);
                  const isConnector = group.name === "Connector Layer";

                  return (
                    <button
                      key={svc.name}
                      type="button"
                      onClick={() => setSelectedService(svc.name)}
                      className="w-full flex items-center justify-between p-4 rounded-lg hover:bg-[#1f1e2a]/60 transition-all duration-300 text-left"
                      style={glassPanel}
                    >
                      <div className="flex items-center gap-5">
                        <div
                          className="w-10 h-10 rounded-lg flex items-center justify-center"
                          style={{ backgroundColor: `${group.color}10`, color: group.color }}
                        >
                          <span className="material-symbols-outlined text-xl">{svc.icon}</span>
                        </div>
                        <div>
                          <div className="flex items-center gap-3">
                            <span className="font-mono font-medium text-sm text-on-surface">{svc.name}</span>
                            <span className={`text-[10px] px-2 py-0.5 rounded ${badge.bg} ${badge.text} border ${badge.border} font-mono`}>
                              {svc.language}
                            </span>
                          </div>
                          {!isConnector && (
                            <p className="text-xs text-outline mt-1 font-body">{svc.description}</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-8">
                        <div className="flex items-center gap-2">
                          <div className={`w-2 h-2 rounded-full ${st.dot} ${st.pulse ? "healthy-pulse" : ""}`} />
                          {!isConnector && (
                            <span className={`text-[10px] uppercase font-mono tracking-wider ${st.labelColor}`}>
                              {st.label}
                            </span>
                          )}
                        </div>
                        <span className="text-xs font-headline font-bold text-primary-fixed hover:text-white transition-colors">
                          View
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}

          {/* Bento Stats Footer */}
          <footer className="pt-10 grid grid-cols-1 md:grid-cols-3 gap-4 border-t border-outline-variant/15">
            <div className="rounded-xl p-6 flex flex-col justify-center" style={glassPanel}>
              <p className="text-[10px] font-mono uppercase tracking-widest text-outline mb-2">Total Services</p>
              <p className="text-4xl font-headline font-bold text-on-surface">{ALL_SERVICES.length}</p>
            </div>
            <div className="rounded-xl p-6 flex flex-col justify-center" style={glassPanel}>
              <p className="text-[10px] font-mono uppercase tracking-widest text-outline mb-2">Healthy</p>
              <div className="flex items-end gap-3">
                <p className="text-4xl font-headline font-bold text-on-surface">{healthyCount}</p>
                <div className="w-2.5 h-2.5 rounded-full bg-secondary mb-2 healthy-pulse" />
              </div>
            </div>
            <div className="rounded-xl p-6 flex flex-col justify-center" style={glassPanel}>
              <p className="text-[10px] font-mono uppercase tracking-widest text-outline mb-3">Languages</p>
              <p className="text-sm font-mono text-primary-fixed-dim">
                {languages.map(([lang, n]) => `${lang} (${n})`).join(" · ")}
              </p>
              <div className="flex gap-1 mt-4">
                {languages.map(([lang, n]) => (
                  <div
                    key={lang}
                    className={`h-1 rounded-full ${badgeForLanguage(lang).bg}`}
                    style={{ flex: n }}
                  />
                ))}
              </div>
            </div>
          </footer>
        </div>
      </main>

      {/* ── Service Detail Slide-Over ──────────────────────────────────── */}
      {selectedService && selectedDef && (
        <>
          {/* Overlay */}
          <div
            className="fixed inset-0 bg-black/50 z-40 backdrop-blur-sm"
            onClick={() => setSelectedService(null)}
          />

          {/* Panel */}
          <aside
            className="fixed right-0 top-0 h-full w-[520px] z-50 flex flex-col shadow-2xl"
            style={slidePanel}
          >
            {/* Header */}
            <div className="p-8 pb-6 flex flex-col gap-6 relative">
              <button
                onClick={() => setSelectedService(null)}
                className="absolute top-6 right-6 p-2 rounded-full hover:bg-surface-bright/50 transition-colors text-on-surface-variant"
                aria-label="Close panel"
              >
                <span className="material-symbols-outlined">close</span>
              </button>

              <div className="flex items-start gap-5">
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center border"
                  style={{
                    backgroundColor: `${LAYER_GROUPS.find((g) => g.services.includes(selectedDef))?.color ?? "#1963b3"}20`,
                    borderColor: `${LAYER_GROUPS.find((g) => g.services.includes(selectedDef))?.color ?? "#1963b3"}33`,
                  }}
                >
                  <span className="material-symbols-outlined text-primary text-3xl">
                    {selectedDef.icon}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-3">
                    <h2 className="font-headline text-2xl font-bold text-on-surface tracking-tight">
                      {selectedDef.name}
                    </h2>
                    {(() => {
                      const st = statusDot(getStatus(selectedDef.name));
                      return (
                        <div className={`flex items-center gap-2 px-2.5 py-0.5 rounded-full ${
                          st.dot === "bg-secondary" ? "bg-secondary/10 border border-secondary/20" :
                          st.dot === "bg-tertiary" ? "bg-tertiary/10 border border-tertiary/20" :
                          st.dot === "bg-error" ? "bg-error/10 border border-error/20" :
                          "bg-surface-container-highest border border-white/10"
                        }`}>
                          <div className={`w-2 h-2 rounded-full ${st.dot} ${st.pulse ? "healthy-pulse" : ""}`} />
                          <span className={`text-[10px] font-bold uppercase tracking-widest ${st.labelColor}`}>
                            {st.label}
                          </span>
                        </div>
                      );
                    })()}
                  </div>
                  <div className="flex gap-2">
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-surface-container-highest text-on-surface-variant uppercase tracking-wider">
                      {selectedDef.language}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-surface-container-highest text-on-surface-variant uppercase tracking-wider">
                      {selectedDef.layer} Layer
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-8 pb-8 space-y-8 custom-scrollbar">
              {/* Overview */}
              <section>
                <h3 className="font-headline text-xs font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-4">
                  Overview
                </h3>
                <div className="grid grid-cols-2 gap-px bg-outline-variant/10 rounded-xl overflow-hidden border border-outline-variant/15">
                  <div className="bg-surface-container p-5 flex flex-col gap-1">
                    <span className="text-[11px] text-on-surface-variant uppercase font-medium">Port</span>
                    <span className="font-mono text-sm text-primary">{selectedDef.port}</span>
                  </div>
                  <div className="bg-surface-container p-5 flex flex-col gap-1">
                    <span className="text-[11px] text-on-surface-variant uppercase font-medium">Health Endpoint</span>
                    <span className="font-mono text-sm text-primary">{selectedDef.healthEndpoint}</span>
                  </div>
                  <div className="bg-surface-container p-5 flex flex-col gap-1">
                    <span className="text-[11px] text-on-surface-variant uppercase font-medium">Response time</span>
                    <span className="text-lg font-bold text-on-surface font-headline tracking-tight">
                      {rowFor(selectedDef).latencyMs !== null ? `${rowFor(selectedDef).latencyMs} ms` : "—"}
                    </span>
                  </div>
                  <div className="bg-surface-container p-5 flex flex-col gap-1">
                    <span className="text-[11px] text-on-surface-variant uppercase font-medium">Last checked</span>
                    <span className="text-lg font-bold text-on-surface font-headline tracking-tight">
                      {rowFor(selectedDef).checkedAt
                        ? new Date(rowFor(selectedDef).checkedAt as string).toLocaleTimeString()
                        : "—"}
                    </span>
                  </div>
                </div>
              </section>

              {/* Configuration */}
              <section>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-headline text-xs font-bold text-on-surface-variant uppercase tracking-[0.2em]">
                    Configuration
                  </h3>
                  <div className="relative group">
                    <button
                      disabled
                      className="flex items-center gap-2 px-3 py-1.5 rounded bg-surface-container-high text-on-surface-variant/40 cursor-not-allowed text-xs font-bold transition-all"
                    >
                      <span className="material-symbols-outlined text-sm">edit</span>
                      Edit Config
                    </button>
                    <div className="absolute bottom-full right-0 mb-2 px-3 py-2 bg-surface-bright text-[11px] text-on-surface whitespace-nowrap rounded opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-xl">
                      Managed via deployment
                    </div>
                  </div>
                </div>
                <div className="bg-surface-container-lowest/50 rounded-xl p-4 flex flex-col gap-3 border border-outline-variant/5">
                  {selectedDef.envVars.map((env, i) => (
                    <div key={env.key}>
                      {i > 0 && <div className="h-px bg-outline-variant/10 mb-3" />}
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs text-on-surface-variant">{env.key}</span>
                        {env.masked ? (
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-on-surface-variant/50">
                              {visibleSecrets.has(env.key) ? env.value : "••••••••••••"}
                            </span>
                            <button
                              onClick={() => toggleSecret(env.key)}
                              className="text-on-surface-variant hover:text-white transition-colors"
                              aria-label={visibleSecrets.has(env.key) ? "Hide value" : "Show value"}
                            >
                              <span className="material-symbols-outlined text-base">
                                {visibleSecrets.has(env.key) ? "visibility_off" : "visibility"}
                              </span>
                            </button>
                          </div>
                        ) : (
                          <span className={`font-mono text-xs ${
                            env.value.startsWith("nats://") || env.value.startsWith("http") || env.value.startsWith("/")
                              ? "text-primary"
                              : "text-tertiary"
                          }`}>
                            {env.value}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Dependencies */}
              {selectedDef.dependencies.length > 0 && (
                <section>
                  <h3 className="font-headline text-xs font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-4">
                    Dependencies
                  </h3>
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-2 px-3 py-2 bg-surface-container rounded-lg border border-primary/20">
                      <span className="material-symbols-outlined text-sm text-primary">{selectedDef.icon}</span>
                      <span className="text-xs font-bold text-on-surface">{selectedDef.name}</span>
                    </div>
                    {selectedDef.dependencies.map((dep) => (
                      <div key={dep.name} className="contents">
                        <span className="material-symbols-outlined text-on-surface-variant/30 text-sm">
                          arrow_forward
                        </span>
                        <button
                          onClick={() => setSelectedService(dep.name)}
                          className="flex items-center gap-2 px-3 py-2 bg-surface-container-low rounded-lg border border-outline-variant/10 hover:border-primary/30 transition-colors"
                        >
                          <span className="material-symbols-outlined text-sm text-on-surface-variant">
                            {dep.icon}
                          </span>
                          <span className="text-xs font-bold text-on-surface">{dep.name}</span>
                        </button>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>

            {/* Footer */}
            <div className="p-8 pt-6 border-t border-outline-variant/10 bg-surface-container-low/80 backdrop-blur-md flex gap-4">
              <a
                href={`/observability/logs`}
                className="flex-1 flex items-center justify-center gap-2 h-11 border border-outline-variant/40 rounded-lg text-sm font-bold text-on-surface hover:bg-surface-bright transition-colors"
              >
                <span className="material-symbols-outlined text-lg">terminal</span>
                View Logs
              </a>
            </div>
          </aside>
        </>
      )}

      {/* Pulse animation style */}
      <style jsx>{`
        .healthy-pulse {
          box-shadow: 0 0 0 0 rgba(123, 220, 123, 0.7);
          animation: pulse 2s infinite;
        }
        @keyframes pulse {
          0% { box-shadow: 0 0 0 0 rgba(123, 220, 123, 0.4); }
          70% { box-shadow: 0 0 0 6px rgba(123, 220, 123, 0); }
          100% { box-shadow: 0 0 0 0 rgba(123, 220, 123, 0); }
        }
      `}</style>
    </>
  );
}
