"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type EdgeMarkerType,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";

/**
 * Pipeline page — live React Flow graph of phantom's component
 * topology, plus a Component Status table and a Recent Traffic feed.
 *
 * Why React Flow: hand-coded SVG keeps strokes/labels in raw SVG
 * primitives, which makes theme-aware contrast finicky, and the
 * polished "looks like a real diagram" aesthetic (auto-routed edges,
 * drag/zoom, per-node hover states) comes for free with React Flow.
 * Our 12 static nodes fit cleanly into its custom-node API.
 *
 * Status colors are CSS tokens (--status-ok / -degraded / -failed
 * / -checking) defined for both themes in globals.css. Dark uses the
 * original luminous accents; light flips to deeper, AA-contrast tones.
 *
 * Health probes go through /api/agent/health — that is what makes
 * xlog and caldera read correctly. No browser →
 * container-internal-hostname fetches anywhere.
 */

type Status = "ok" | "degraded" | "failed" | "checking";

interface NodeData extends Record<string, unknown> {
  label: string;
  sub: string;
  status: Status;
  /** Probe id from /api/agent/health to map status from. */
  probeId?: string;
}

interface ProbeResult {
  id: string;
  url: string;
  status: "ok" | "failed" | "skipped";
  httpStatus?: number;
  latencyMs?: number;
  error?: string;
}

interface AuditEvent {
  ts?: string;
  action?: string;
  target?: string;
  actor?: string;
}

// ── Layout ──────────────────────────────────────────────────────────
//
// React Flow needs explicit node positions when the layout is static
// (no auto-layout engine like dagre wired up). We keep the same
// 3-lane layout from the SVG version: REQUEST top, STORAGE middle,
// CONNECTORS bottom. The fan-out from MCP to stores spreads
// symmetrically because all six store nodes share the same y and the
// MCP sits centered above them.

const NODE_W = 200;
const NODE_H_DEFAULT = 84;
const NODE_H_STORE = 70;

const NODES_DEF: Array<Omit<Node<NodeData>, "data"> & { data: NodeData }> = [
  // Lane 1 — request flow (y=40)
  {
    id: "browser",
    type: "phantomNode",
    position: { x: 60, y: 40 },
    data: { label: "Browser", sub: "operator UI", status: "ok" },
    draggable: true,
  },
  {
    id: "agent",
    type: "phantomNode",
    position: { x: 320, y: 40 },
    data: { label: "phantom-agent", sub: "Next.js 15 / :3000", status: "checking", probeId: "phantom-agent" },
    draggable: true,
  },
  {
    id: "mcp",
    type: "phantomNode",
    position: { x: 580, y: 40 },
    data: { label: "phantom-mcp", sub: "FastMCP / :8080", status: "checking", probeId: "phantom-mcp" },
    draggable: true,
  },
  {
    id: "vertex",
    type: "phantomNode",
    position: { x: 840, y: 40 },
    data: { label: "Model provider", sub: "Gemini / Claude / OpenAI", status: "checking" },
    draggable: true,
  },

  // Lane 2 — storage (y=220) — 6 stores in a single row, fanned from MCP
  { id: "audit", type: "phantomStore", position: { x: 30, y: 220 }, data: { label: "audit_log", sub: "sqlite", status: "checking" }, draggable: true },
  { id: "memory", type: "phantomStore", position: { x: 220, y: 220 }, data: { label: "memory_store", sub: "sqlite + vector", status: "checking" }, draggable: true },
  { id: "secrets", type: "phantomStore", position: { x: 410, y: 220 }, data: { label: "secret_store", sub: "AES-256-GCM", status: "checking" }, draggable: true },
  { id: "settings", type: "phantomStore", position: { x: 600, y: 220 }, data: { label: "settings_store", sub: "sqlite", status: "checking" }, draggable: true },
  { id: "sessions", type: "phantomStore", position: { x: 790, y: 220 }, data: { label: "sessions", sub: "sqlite", status: "checking" }, draggable: true },
  { id: "jobs", type: "phantomStore", position: { x: 980, y: 220 }, data: { label: "jobs", sub: "sqlite cron", status: "checking" }, draggable: true },

  // Lane 3 — connectors (y=380) — 3 connectors centered under MCP
  { id: "xlog", type: "phantomNode", position: { x: 320, y: 380 }, data: { label: "xlog", sub: "synthetic logs / :8000", status: "checking", probeId: "xlog-api" }, draggable: true },
  { id: "caldera", type: "phantomNode", position: { x: 580, y: 380 }, data: { label: "caldera", sub: "MITRE adversary / :8888", status: "checking", probeId: "caldera" }, draggable: true },
  { id: "xsiam", type: "phantomNode", position: { x: 840, y: 380 }, data: { label: "xsiam", sub: "Cortex PAPI", status: "checking" }, draggable: true },
];

const EDGES_DEF: Edge[] = [
  { id: "browser->agent", source: "browser", target: "agent", label: "HTTPS" },
  { id: "agent->mcp", source: "agent", target: "mcp", label: "Bearer + JSON" },
  { id: "agent->vertex", source: "agent", target: "vertex", label: "HTTPS" },
  { id: "mcp->audit", source: "mcp", target: "audit" },
  { id: "mcp->memory", source: "mcp", target: "memory" },
  { id: "mcp->secrets", source: "mcp", target: "secrets" },
  { id: "mcp->settings", source: "mcp", target: "settings" },
  { id: "mcp->sessions", source: "mcp", target: "sessions" },
  { id: "mcp->jobs", source: "mcp", target: "jobs" },
  { id: "mcp->xlog", source: "mcp", target: "xlog", label: "GraphQL" },
  { id: "mcp->caldera", source: "mcp", target: "caldera", label: "v2 REST" },
  { id: "mcp->xsiam", source: "mcp", target: "xsiam", label: "PAPI" },
];

const STATUS_LABEL: Record<Status, string> = {
  ok: "Healthy",
  degraded: "Degraded",
  failed: "Failed",
  checking: "Probing",
};

const STATUS_VAR: Record<Status, string> = {
  ok: "var(--status-ok)",
  degraded: "var(--status-degraded)",
  failed: "var(--status-failed)",
  checking: "var(--status-checking)",
};

const STATUS_SOFT_VAR: Record<Status, string> = {
  ok: "var(--status-ok-soft)",
  degraded: "var(--status-degraded-soft)",
  failed: "var(--status-failed-soft)",
  checking: "var(--status-checking-soft)",
};

function relativeAge(iso?: string): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

// ── Custom node components ──────────────────────────────────────────
//
// React Flow renders whatever JSX you put inside a custom node, so the
// whole "pretty box" treatment lives here. Borders + status dot use
// the theme-aware --status-* vars. Handles are positioned on edges so
// edges enter/exit cleanly.

function PhantomNode({ data }: NodeProps<Node<NodeData>>) {
  const stroke = STATUS_VAR[data.status];
  const dotOpacity = data.status === "checking" ? 0.6 : 1;
  return (
    <div
      className="rounded-xl px-4 py-3 transition-shadow hover:shadow-lg"
      style={{
        width: NODE_W,
        height: NODE_H_DEFAULT,
        background: "var(--graph-node-bg)",
        border: `1.5px solid ${stroke}`,
        boxShadow: "var(--glass-shadow, 0 1px 4px rgba(0,0,0,0.04))",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="r" style={{ opacity: 0 }} />
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full shrink-0"
          style={{
            background: stroke,
            opacity: dotOpacity,
            animation: data.status === "checking" ? "phantom-pulse 1.5s ease-in-out infinite" : undefined,
          }}
        />
        <div className="font-semibold text-sm text-on-surface truncate">{data.label}</div>
      </div>
      <div className="text-[11px] text-on-surface-variant mt-1 truncate">{data.sub}</div>
    </div>
  );
}

function PhantomStore({ data }: NodeProps<Node<NodeData>>) {
  const stroke = STATUS_VAR[data.status];
  const dotOpacity = data.status === "checking" ? 0.6 : 1;
  return (
    <div
      className="rounded-xl px-3 py-2 transition-shadow hover:shadow-lg"
      style={{
        width: 170,
        height: NODE_H_STORE,
        background: "var(--graph-node-bg)",
        border: `1.5px solid ${stroke}`,
        boxShadow: "var(--glass-shadow, 0 1px 4px rgba(0,0,0,0.04))",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div className="flex items-center gap-2">
        <span
          className="h-1.5 w-1.5 rounded-full shrink-0"
          style={{
            background: stroke,
            opacity: dotOpacity,
            animation: data.status === "checking" ? "phantom-pulse 1.5s ease-in-out infinite" : undefined,
          }}
        />
        <div className="font-semibold text-[13px] text-on-surface truncate">{data.label}</div>
      </div>
      <div className="text-[10px] text-on-surface-variant/80 mt-0.5 truncate">{data.sub}</div>
    </div>
  );
}

const NODE_TYPES = {
  phantomNode: PhantomNode,
  phantomStore: PhantomStore,
};

// ── Page ────────────────────────────────────────────────────────────

export default function PipelinePage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>(NODES_DEF as Node<NodeData>[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState(decorateEdges(EDGES_DEF, new Set()));
  const [probes, setProbes] = useState<ProbeResult[]>([]);
  const [activeEdges, setActiveEdges] = useState<Set<string>>(new Set());
  const [recentEvents, setRecentEvents] = useState<AuditEvent[]>([]);
  const [lastProbeAt, setLastProbeAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function probeOnce() {
      // /api/agent/health does the container-internal probes server-side
      // and returns a normalized array. Don't fetch external/internal
      // hostnames from the browser.
      let probeArr: ProbeResult[] = [];
      try {
        const r = await fetch("/api/agent/health", { cache: "no-store" });
        if (r.ok) {
          const data = (await r.json()) as { probes?: ProbeResult[] };
          probeArr = data.probes ?? [];
        }
      } catch {
        // empty
      }

      const probeStatus = new Map<string, Status>();
      for (const p of probeArr) {
        if (p.status === "ok") probeStatus.set(p.id, "ok");
        else if (p.status === "failed") probeStatus.set(p.id, "failed");
        else probeStatus.set(p.id, "checking");
      }

      // Stores inherit MCP's status — same model as before.
      const mcpStatus = probeStatus.get("phantom-mcp") ?? "checking";
      const STORE_IDS = new Set(["audit", "memory", "secrets", "settings", "sessions", "jobs"]);

      // Recent audit events for traffic pulses + activity feed.
      let active = new Set<string>();
      let events: AuditEvent[] = [];
      try {
        const r = await fetch("/api/agent/audit?limit=50", { cache: "no-store" });
        if (r.ok) {
          const data = (await r.json()) as { events?: AuditEvent[] };
          events = data.events ?? [];
          const cutoff = Date.now() - 60_000;
          for (const e of events) {
            if (!e.ts) continue;
            const t = Date.parse(e.ts);
            if (!Number.isFinite(t) || t <= cutoff) continue;
            const target = String(e.target ?? "");
            if (target.startsWith("tool:xlog.")) active.add("mcp->xlog");
            if (target.startsWith("tool:caldera.")) active.add("mcp->caldera");
            if (target.startsWith("tool:xsiam.")) active.add("mcp->xsiam");
            if (e.action === "tool_call") active.add("agent->mcp");
            if (e.action === "chat_append") active.add("agent->vertex");
            if (e.action === "memory_store" || e.action === "memory_search") active.add("mcp->memory");
            if (e.action === "secret_set" || e.action === "secret_get") active.add("mcp->secrets");
            if (e.action === "settings_changed") active.add("mcp->settings");
          }
        }
      } catch {
        // empty
      }

      if (cancelled) return;

      // Apply status updates to existing nodes (preserve any drag
      // positions the operator may have introduced).
      setNodes((curr) =>
        curr.map((n) => {
          let next: Status;
          if (n.id === "browser") next = "ok";
          else if (n.data.probeId && probeStatus.has(n.data.probeId))
            next = probeStatus.get(n.data.probeId)!;
          else if (STORE_IDS.has(n.id)) next = mcpStatus;
          else next = "checking";
          return { ...n, data: { ...n.data, status: next } };
        }),
      );
      setEdges(decorateEdges(EDGES_DEF, active));
      setProbes(probeArr);
      setActiveEdges(active);
      setRecentEvents(events.slice(0, 12));
      setLastProbeAt(new Date().toISOString());
    }

    void probeOnce();
    const t = setInterval(() => void probeOnce(), 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [setNodes, setEdges]);

  // Counts for the summary strip.
  const summary = useMemo(() => {
    let healthy = 0;
    let degraded = 0;
    let failed = 0;
    let checking = 0;
    for (const n of nodes) {
      const s = n.data.status;
      if (s === "ok") healthy++;
      else if (s === "degraded") degraded++;
      else if (s === "failed") failed++;
      else checking++;
    }
    return {
      healthy,
      degraded,
      failed,
      checking,
      activeEdges: activeEdges.size,
    };
  }, [nodes, activeEdges]);

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <span className="material-symbols-outlined text-2xl text-primary">account_tree</span>
          <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Pipeline</h1>
        </div>
        <p className="text-sm text-on-surface-variant ml-9">
          Phantom component graph with live readiness + traffic. Refresh: 5s. Drag nodes to rearrange. Pulsing links show paths active in the last 60s.
          {lastProbeAt && (
            <span className="ml-2 text-on-surface-variant/60">
              · last probe {relativeAge(lastProbeAt)}
            </span>
          )}
        </p>
      </div>

      {/* ── Summary strip ───────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryTile icon="monitor_heart" label="Healthy" value={summary.healthy} tone="ok" />
        <SummaryTile
          icon="warning"
          label="Degraded / Failed"
          value={summary.degraded + summary.failed}
          tone={summary.failed > 0 ? "failed" : summary.degraded > 0 ? "degraded" : "ok"}
        />
        <SummaryTile icon="hourglass_top" label="Probing" value={summary.checking} tone="checking" />
        <SummaryTile
          icon="bolt"
          label="Active paths (60s)"
          value={summary.activeEdges}
          tone={summary.activeEdges > 0 ? "ok" : "checking"}
        />
      </div>

      {/* ── React Flow graph ────────────────────────────────── */}
      <div
        className="rounded-2xl overflow-hidden phantom-flow-shell"
        style={{
          background: "var(--glass-bg-strong)",
          backdropFilter: "blur(12px)",
          border: "0.5px solid var(--glass-border)",
          height: 540,
        }}
      >
        {/* Lane labels — faint markers above the canvas so it's
            obvious which row is what. */}
        <div className="px-6 pt-4 flex justify-between text-[10px] uppercase tracking-[0.2em] text-on-surface-variant/45 font-bold">
          <span>request</span>
          <span>storage</span>
          <span>connectors</span>
        </div>
        <div style={{ height: "calc(100% - 32px)" }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable
            nodesConnectable={false}
            edgesFocusable={false}
            panOnDrag
            zoomOnScroll={false}
            zoomOnPinch
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--graph-edge)" />
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-on-surface-variant">
        <LegendDot tone="ok" label="healthy" />
        <LegendDot tone="degraded" label="degraded" />
        <LegendDot tone="failed" label="failed" />
        <LegendDot tone="checking" label="probing" />
        <span className="flex items-center gap-2 ml-auto">
          <span className="h-1 w-6" style={{ background: "var(--graph-edge-active)" }} />
          traffic in last 60s
        </span>
      </div>

      {/* ── Component status table ──────────────────────────── */}
      <section
        className="rounded-2xl overflow-hidden"
        style={{
          background: "var(--glass-bg-strong)",
          backdropFilter: "blur(12px)",
          border: "0.5px solid var(--glass-border)",
        }}
      >
        <header className="px-5 py-3 border-b border-outline-variant/30 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-primary">checklist</span>
            <h2 className="font-headline text-sm font-bold tracking-tight text-on-surface uppercase">
              Component Status
            </h2>
          </div>
          <span className="text-[10px] font-mono text-on-surface-variant/60">
            {probes.length} probe{probes.length === 1 ? "" : "s"}
          </span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-container-low text-on-surface-variant text-[10px] uppercase tracking-wider">
              <tr>
                <th className="px-5 py-2 text-left font-semibold">Component</th>
                <th className="px-5 py-2 text-left font-semibold">Status</th>
                <th className="px-5 py-2 text-left font-semibold">Endpoint</th>
                <th className="px-5 py-2 text-right font-semibold">HTTP</th>
                <th className="px-5 py-2 text-right font-semibold">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/20">
              {NODES_DEF.map((nd) => {
                const cur = nodes.find((n) => n.id === nd.id);
                const status = (cur?.data.status ?? "checking") as Status;
                const probe = probes.find((p) => p.id === nd.data.probeId);
                return (
                  <tr key={nd.id} className="hover:bg-surface-container-low/40 transition-colors">
                    <td className="px-5 py-2.5">
                      <div className="font-mono text-on-surface text-xs font-semibold">
                        {nd.data.label}
                      </div>
                      <div className="text-[10px] text-on-surface-variant/60">{nd.data.sub}</div>
                    </td>
                    <td className="px-5 py-2.5">
                      <StatusPill status={status} />
                    </td>
                    <td className="px-5 py-2.5 font-mono text-[11px] text-on-surface-variant truncate max-w-[280px]">
                      {probe?.url ?? <span className="text-on-surface-variant/40">— inferred —</span>}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-[11px] text-on-surface-variant">
                      {probe?.httpStatus ?? "—"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-[11px] text-on-surface-variant">
                      {probe?.latencyMs != null ? `${probe.latencyMs}ms` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Recent traffic feed ─────────────────────────────── */}
      <section
        className="rounded-2xl overflow-hidden"
        style={{
          background: "var(--glass-bg-strong)",
          backdropFilter: "blur(12px)",
          border: "0.5px solid var(--glass-border)",
        }}
      >
        <header className="px-5 py-3 border-b border-outline-variant/30 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-primary">bolt</span>
            <h2 className="font-headline text-sm font-bold tracking-tight text-on-surface uppercase">
              Recent Traffic
            </h2>
          </div>
          <span className="text-[10px] font-mono text-on-surface-variant/60">
            {recentEvents.length} of last 50
          </span>
        </header>
        {recentEvents.length === 0 ? (
          <div className="px-5 py-8 text-sm text-center text-on-surface-variant/60">
            No recent audit events. Trigger a chat or run a tool to populate this feed.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-container-low text-on-surface-variant text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="px-5 py-2 text-left font-semibold">When</th>
                  <th className="px-5 py-2 text-left font-semibold">Action</th>
                  <th className="px-5 py-2 text-left font-semibold">Target</th>
                  <th className="px-5 py-2 text-left font-semibold">Actor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/20">
                {recentEvents.map((evt, i) => (
                  <tr key={`${evt.ts}-${i}`} className="hover:bg-surface-container-low/40 transition-colors">
                    <td className="px-5 py-2 font-mono text-[11px] text-on-surface-variant whitespace-nowrap">
                      {relativeAge(evt.ts)}
                    </td>
                    <td className="px-5 py-2 font-mono text-[11px] text-primary">{evt.action ?? "—"}</td>
                    <td className="px-5 py-2 font-mono text-[11px] text-on-surface truncate max-w-[420px]">
                      {evt.target ?? "—"}
                    </td>
                    <td className="px-5 py-2 font-mono text-[11px] text-on-surface-variant">
                      {evt.actor ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <style jsx global>{`
        @keyframes phantom-pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
        @keyframes phantom-edge-flow {
          to { stroke-dashoffset: -20; }
        }
        .phantom-flow-shell .react-flow__edge-path-active {
          stroke-dasharray: 6 4;
          animation: phantom-edge-flow 0.9s linear infinite;
        }
        /* Theme-aware controls — the default React Flow controls have
           a hardcoded white bg that fights the navy dark theme. Lift
           them onto the same glass surface as everything else. */
        .phantom-flow-shell .react-flow__controls {
          background: var(--glass-bg-strong);
          border: 0.5px solid var(--glass-border);
          backdrop-filter: blur(12px);
          border-radius: 8px;
          overflow: hidden;
          box-shadow: var(--glass-shadow);
        }
        .phantom-flow-shell .react-flow__controls-button {
          background: transparent;
          border-bottom: 0.5px solid var(--glass-border);
          color: var(--graph-text-primary);
          fill: var(--graph-text-primary);
        }
        .phantom-flow-shell .react-flow__controls-button:hover {
          background: var(--glass-bg-elev);
        }
      `}</style>
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function decorateEdges(defs: Edge[], active: Set<string>): Edge[] {
  return defs.map((e) => {
    const isActive = active.has(e.id);
    const arrowMarker: EdgeMarkerType = {
      type: MarkerType.ArrowClosed,
      color: isActive ? "var(--graph-edge-active)" : "var(--graph-edge)",
      width: 14,
      height: 14,
    };
    return {
      ...e,
      type: "smoothstep",
      animated: isActive,
      style: {
        stroke: isActive ? "var(--graph-edge-active)" : "var(--graph-edge)",
        strokeWidth: isActive ? 2 : 1.2,
        opacity: isActive ? 0.95 : 0.65,
      },
      labelStyle: {
        fill: "var(--graph-text-muted)",
        fontSize: 10,
        opacity: 0.85,
      },
      labelBgStyle: { fill: "var(--graph-node-bg)", opacity: 0.7 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 3,
      markerEnd: arrowMarker,
      className: isActive ? "react-flow__edge-path-active" : undefined,
    };
  });
}

function StatusPill({ status }: { status: Status }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
      style={{
        color: STATUS_VAR[status],
        background: STATUS_SOFT_VAR[status],
        border: `0.5px solid ${STATUS_VAR[status]}`,
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_VAR[status] }} />
      {STATUS_LABEL[status]}
    </span>
  );
}

function LegendDot({ tone, label }: { tone: Status; label: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="h-2 w-2 rounded-full" style={{ background: STATUS_VAR[tone] }} />
      {label}
    </span>
  );
}

function SummaryTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: string;
  label: string;
  value: number;
  tone: Status;
}) {
  return (
    <div
      className="rounded-2xl p-4 flex items-center gap-3"
      style={{
        background: "var(--glass-bg-strong)",
        backdropFilter: "blur(12px)",
        border: "0.5px solid var(--glass-border)",
      }}
    >
      <div
        className="h-10 w-10 rounded-xl flex items-center justify-center shrink-0"
        style={{
          background: STATUS_SOFT_VAR[tone],
          border: `0.5px solid ${STATUS_VAR[tone]}`,
        }}
      >
        <span className="material-symbols-outlined text-lg" style={{ color: STATUS_VAR[tone] }}>
          {icon}
        </span>
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">{label}</div>
        <div className="text-2xl font-headline font-bold text-on-surface leading-none mt-1">
          {value}
        </div>
      </div>
    </div>
  );
}
