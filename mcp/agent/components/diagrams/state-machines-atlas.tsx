"use client";

/**
 * Phantom State Machines Atlas.
 *
 * Three side-by-side state machines: Task · Connector · Session. The
 * point is the architectural symmetry — Phantom uses the same
 * persistence + state-transition pattern (single row per entity,
 * audit row on every transition) across multiple subsystems.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.sma .column-bg {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
}
.dgm-root.sma .column-title {
  fill: var(--dgm-text-main);
  font-size: 16px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
  letter-spacing: -0.01em;
}
.dgm-root.sma .column-sub {
  fill: var(--dgm-text-soft);
  font-size: 11.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sma .state-bubble {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.6;
}
.dgm-root.sma .state-bubble.start {
  stroke: var(--dgm-edge-operator);
}
.dgm-root.sma .state-bubble.success {
  stroke: var(--dgm-state-success);
  fill: rgba(69, 212, 131, 0.10);
}
.dgm-root.sma .state-bubble.error {
  stroke: var(--dgm-state-error);
  fill: rgba(255, 122, 138, 0.08);
}
.dgm-root.sma .state-bubble.warn {
  stroke: var(--dgm-state-warn);
  fill: rgba(247, 183, 49, 0.08);
}
.dgm-root.sma .state-bubble.terminal {
  stroke: var(--dgm-text-muted);
  fill: var(--dgm-bg-2);
}
.dgm-root.sma .state-name {
  fill: var(--dgm-text-main);
  font-size: 13.5px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sma .state-detail {
  fill: var(--dgm-text-soft);
  font-size: 10.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sma .transition {
  fill: none;
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.6;
}
.dgm-root.sma .transition.error { stroke: var(--dgm-state-error); }
.dgm-root.sma .transition.success { stroke: var(--dgm-state-success); }
.dgm-root.sma .transition.warn { stroke: var(--dgm-state-warn); }
.dgm-root.sma .transition.muted {
  stroke: var(--dgm-text-muted);
  stroke-dasharray: 4 4;
}
.dgm-root.sma .transition-label {
  fill: var(--dgm-text-soft);
  font-size: 10.5px;
  font-weight: 600;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sma .audit-tag {
  fill: var(--dgm-edge-shared);
  font-size: 10px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
`;

interface StateNode {
  id: string;
  /** label rendered inside the bubble */
  name: string;
  /** small caption under the bubble */
  detail?: string;
  /** semantic styling */
  variant?: "default" | "start" | "success" | "error" | "warn" | "terminal";
  /** y position within the column */
  y: number;
  /** x offset within the column (from column center, ±) */
  xOffset?: number;
  /** override bubble width (default STATE_W) — useful for compact terminal rows */
  w?: number;
}

interface Transition {
  from: string;
  to: string;
  label: string;
  variant?: "default" | "error" | "success" | "warn" | "muted";
  /** routing: 'straight' (default vertical) | 'curve-right' | 'curve-left' | 'self' */
  route?: "straight" | "curve-right" | "curve-left" | "self";
}

interface Machine {
  title: string;
  sub: string;
  audit: string;
  states: StateNode[];
  transitions: Transition[];
}

const MACHINES: Machine[] = [
  {
    title: "Task",
    sub: "tasks.db · long-running operations",
    audit: "audit: task_created | task_started | task_completed | task_failed | task_aborted",
    states: [
      { id: "pending", name: "pending", detail: "row created · not picked up", variant: "start", y: 80 },
      { id: "running", name: "running", detail: "worker holds the row", variant: "default", y: 220 },
      { id: "succeeded", name: "succeeded", detail: "result_json", variant: "success", y: 410, xOffset: -130, w: 140 },
      { id: "failed", name: "failed", detail: "error column", variant: "error", y: 410, xOffset: 0, w: 140 },
      { id: "aborted", name: "aborted", detail: "operator cancel", variant: "warn", y: 410, xOffset: 130, w: 140 },
    ],
    transitions: [
      { from: "pending", to: "running", label: "worker picks up" },
      { from: "running", to: "succeeded", label: "✓", variant: "success" },
      { from: "running", to: "failed", label: "✗ throws", variant: "error" },
      { from: "running", to: "aborted", label: "cancel", variant: "warn" },
    ],
  },
  {
    title: "Connector",
    sub: "connector_state.db · per-instance health",
    audit: "audit: connector_enabled | connector_disabled | connector_failed | connector_auth_required",
    states: [
      { id: "enabled", name: "enabled", detail: "tools dispatch normally", variant: "success", y: 80 },
      { id: "probed", name: "probed", detail: "transient probe", variant: "default", y: 220, xOffset: -120, w: 150 },
      { id: "failed", name: "failed", detail: "auto-retried", variant: "error", y: 220, xOffset: 120, w: 150 },
      { id: "auth_required", name: "auth_required", detail: "401 · operator must reauth", variant: "warn", y: 360 },
      { id: "disabled", name: "disabled", detail: "operator-paused", variant: "terminal", y: 490 },
    ],
    transitions: [
      { from: "enabled", to: "probed", label: "5-min tick", variant: "muted" },
      { from: "probed", to: "enabled", label: "200 ok", variant: "success" },
      { from: "probed", to: "failed", label: "5xx / timeout", variant: "error" },
      { from: "failed", to: "auth_required", label: "401 detected", variant: "warn" },
      { from: "auth_required", to: "enabled", label: "operator reauth", variant: "success" },
      { from: "enabled", to: "disabled", label: "operator pauses", variant: "muted" },
      { from: "disabled", to: "enabled", label: "operator resumes", variant: "muted" },
    ],
  },
  {
    title: "Session",
    sub: "sessions.db · chat lifecycle",
    audit: "audit: chat_session_* (start/compact/clear/archive)",
    states: [
      { id: "active", name: "active", detail: "messages append", variant: "start", y: 80 },
      { id: "compacted", name: "compacted", detail: "checkpoint inserted", variant: "warn", y: 220 },
      { id: "cleared", name: "cleared", detail: "/clear · still listed", variant: "default", y: 340 },
      { id: "archived", name: "archived", detail: "30-day TTL expiry", variant: "terminal", y: 460 },
    ],
    transitions: [
      { from: "active", to: "compacted", label: "/compress · auto-edge", variant: "warn" },
      { from: "compacted", to: "active", label: "next turn", variant: "success" },
      { from: "active", to: "cleared", label: "/clear", variant: "muted" },
      { from: "cleared", to: "archived", label: "TTL sweep", variant: "muted" },
    ],
  },
];

const VIEW_W = 1520;
const VIEW_H = 920;
const COL_W = 460;
const COL_GAP = 30;
const COL_TOP = 130;
const COL_H = 660;
const STATE_W = 200;
const STATE_H = 56;

const totalCols = MACHINES.length;
const gridW = totalCols * COL_W + (totalCols - 1) * COL_GAP;
const startX = (VIEW_W - gridW) / 2;
const colX = (i: number) => startX + i * (COL_W + COL_GAP);

export function StateMachinesAtlas() {
  return (
    <div className="dgm-root sma">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="sma-title sma-desc"
      >
        <title id="sma-title">State Machines Atlas</title>
        <desc id="sma-desc">
          Three state machines side-by-side: task, connector, session.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="sma-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
          {/* Per-variant arrowheads matching state-line colours */}
          <marker id="sma-ah-success" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-state-success)" />
          </marker>
          <marker id="sma-ah-error" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-state-error)" />
          </marker>
          <marker id="sma-ah-warn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-state-warn)" />
          </marker>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#sma-dot-grid)" />

        {/* Header */}
        <text x="60" y="44" className="title" fontSize="22">
          State Machines Atlas
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Three subsystems share the same shape: single-row entity, transitions
          write audit rows, terminal states are explicit.
        </text>

        {MACHINES.map((m, mi) => {
          const cx = colX(mi) + COL_W / 2;
          // Build a state lookup so we can resolve transition coordinates
          const stateAt = (sid: string) => {
            const s = m.states.find((s) => s.id === sid)!;
            return {
              x: cx + (s.xOffset ?? 0),
              y: COL_TOP + s.y,
            };
          };
          return (
            <g key={m.title}>
              {/* Column background */}
              <rect
                className="column-bg"
                x={colX(mi)}
                y={COL_TOP - 70}
                width={COL_W}
                height={COL_H}
                rx="18"
              />
              {/* Title */}
              <text
                className="column-title"
                x={colX(mi) + 22}
                y={COL_TOP - 36}
              >
                {m.title}
              </text>
              <text
                className="column-sub"
                x={colX(mi) + 22}
                y={COL_TOP - 16}
              >
                {m.sub}
              </text>

              {/* Transitions (drawn first so states stack on top) */}
              {m.transitions.map((t, ti) => {
                const a = stateAt(t.from);
                const b = stateAt(t.to);
                const variant = t.variant ?? "default";
                const stroke =
                  variant === "error"
                    ? "var(--dgm-state-error)"
                    : variant === "success"
                      ? "var(--dgm-state-success)"
                      : variant === "warn"
                        ? "var(--dgm-state-warn)"
                        : variant === "muted"
                          ? "var(--dgm-text-muted)"
                          : "var(--dgm-edge-operator)";
                const arrowMarker =
                  variant === "error"
                    ? "url(#sma-ah-error)"
                    : variant === "success"
                      ? "url(#sma-ah-success)"
                      : variant === "warn"
                        ? "url(#sma-ah-warn)"
                        : "url(#dgm-arrow-operator)";
                const dasharray = variant === "muted" ? "4 4" : undefined;
                // Compute arrow path. If states are in same column (no x diff), use a curve when reciprocal
                const dx = b.x - a.x;
                const dy = b.y - a.y;
                const isReverse = dy < 0;
                // Lateral offset for label: only applied for vertically-
                // adjacent reverse-direction pairs (so the two labels don't
                // overlap at the same midpoint).
                const isVertical = Math.abs(dx) < 5;
                const offset = isVertical ? (isReverse ? -34 : 34) : 0;
                let d: string;
                if (Math.abs(dx) < 5) {
                  // Vertical: curve slightly to the side if multiple transitions exist between same pair
                  d = `M ${a.x} ${a.y + (isReverse ? -STATE_H / 2 : STATE_H / 2)} L ${b.x} ${b.y + (isReverse ? STATE_H / 2 : -STATE_H / 2)}`;
                } else {
                  // Diagonal
                  d = `M ${a.x} ${a.y + STATE_H / 2} L ${b.x} ${b.y - STATE_H / 2}`;
                }
                // Label: midpoint with slight offset
                const mx = (a.x + b.x) / 2 + offset;
                const my = (a.y + b.y) / 2;
                return (
                  <g key={`${mi}-t-${ti}`}>
                    <path
                      className="transition"
                      d={d}
                      style={{ stroke, strokeDasharray: dasharray }}
                      markerEnd={arrowMarker}
                    />
                    <text
                      className="transition-label"
                      x={mx}
                      y={my}
                      textAnchor="middle"
                    >
                      {t.label}
                    </text>
                  </g>
                );
              })}

              {/* States */}
              {m.states.map((s) => {
                const sx = cx + (s.xOffset ?? 0);
                const sy = COL_TOP + s.y;
                const w = s.w ?? STATE_W;
                const variantClass = s.variant ?? "default";
                return (
                  <g key={`${mi}-s-${s.id}`}>
                    <rect
                      className={`state-bubble ${variantClass}`}
                      x={sx - w / 2}
                      y={sy - STATE_H / 2}
                      width={w}
                      height={STATE_H}
                      rx={STATE_H / 2}
                    />
                    <text
                      className="state-name"
                      x={sx}
                      y={sy + 1}
                      textAnchor="middle"
                    >
                      {s.name}
                    </text>
                    {s.detail && (
                      <text
                        className="state-detail"
                        x={sx}
                        y={sy + STATE_H / 2 + 16}
                        textAnchor="middle"
                      >
                        {s.detail}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Audit tag at the bottom of column */}
              <text
                className="audit-tag"
                x={colX(mi) + 22}
                y={COL_TOP + COL_H - 88}
              >
                {m.audit}
              </text>
            </g>
          );
        })}

        {/* Footer */}
        <g transform={`translate(60 ${VIEW_H - 60})`}>
          <rect
            x="0"
            y="-18"
            width={VIEW_W - 120}
            height="48"
            rx="14"
            fill="var(--dgm-panel)"
            stroke="var(--dgm-stroke-muted)"
          />
          <text className="legend-title" x="20" y="4">
            The pattern
          </text>
          <text className="legend-text" x="180" y="4">
            One row per entity · transitions ALWAYS write an audit row · terminal
            states are explicit (succeeded/failed/aborted/archived) · operator
            actions take the same edge as the system would, audit-tagged so the
            origin is queryable.
          </text>
        </g>
      </svg>
    </div>
  );
}
