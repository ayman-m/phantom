"use client";

/**
 * Phantom Operator Daily Loop.
 *
 * Cyclical flow showing the operator's typical day-driver loop:
 * Chat → Run scenario → Observe → Refine → Chat again. Three primary
 * surfaces in the cycle, with Jobs (scheduled work) and Hooks (policy)
 * shown as side-branches that automate parts of the loop.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.odl .surface-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-operator);
  stroke-width: 2;
}
.dgm-root.odl .surface-card.observability {
  stroke: var(--dgm-edge-shared);
}
.dgm-root.odl .surface-card.refine {
  stroke: var(--dgm-edge-compose);
}
.dgm-root.odl .surface-icon-bg {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-muted);
}
.dgm-root.odl .surface-icon {
  fill: none;
  stroke: var(--dgm-text-main);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dgm-root.odl .surface-name {
  fill: var(--dgm-text-main);
  font-size: 18px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.odl .surface-route {
  fill: var(--dgm-edge-operator);
  font-size: 12px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.odl .surface-detail {
  fill: var(--dgm-text-soft);
  font-size: 11.5px;
}
.dgm-root.odl .surface-action-pill {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
}
.dgm-root.odl .surface-action-text {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.odl .loop-arrow {
  fill: none;
  stroke: var(--dgm-edge-operator);
  stroke-width: 2.5;
}
.dgm-root.odl .loop-label {
  fill: var(--dgm-edge-operator);
  font-size: 12px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.odl .branch-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-iap);
  stroke-width: 1.6;
  stroke-dasharray: 6 5;
}
.dgm-root.odl .branch-tag {
  fill: var(--dgm-edge-iap);
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.2em;
}
.dgm-root.odl .branch-name {
  fill: var(--dgm-text-main);
  font-size: 14px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.odl .branch-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
}
.dgm-root.odl .branch-edge {
  stroke: var(--dgm-edge-iap);
  stroke-width: 1.6;
  stroke-dasharray: 6 5;
  fill: none;
}
`;

interface Surface {
  id: "chat" | "scenario" | "observe";
  name: string;
  route: string;
  detail: string;
  /** angle in degrees on the cycle (0 = top, going clockwise) */
  angleDeg: number;
  variant?: "default" | "observability" | "refine";
  actions: string[];
  iconPath: React.ReactNode;
}

const SURFACES: Surface[] = [
  {
    id: "chat",
    name: "Chat",
    route: "/  ",
    detail: "describe what you want · agent dispatches tools",
    angleDeg: -90, // top
    variant: "default",
    actions: ["/plan multi-step", "/spawn red-team", "/cost"],
    iconPath: (
      <g>
        <path d="M -9 -4 a 2 2 0 0 1 2 -2 h 14 a 2 2 0 0 1 2 2 v 8 a 2 2 0 0 1 -2 2 h -10 l -4 4 v -4 h -2 a 2 2 0 0 1 -2 -2 z" />
      </g>
    ),
  },
  {
    id: "scenario",
    name: "Run scenario",
    route: "via tool dispatch",
    detail: "xlog ships logs · CALDERA runs adversary · XSIAM XQL",
    angleDeg: 30, // bottom-right
    variant: "default",
    actions: [
      "scenario worker spawn",
      "log webhook → SIEM",
      "operation results",
    ],
    iconPath: (
      <g>
        <polygon points="-7,-7 7,0 -7,7" />
      </g>
    ),
  },
  {
    id: "observe",
    name: "Observability",
    route: "/observability/*",
    detail: "events · traces · metrics · cost · pipeline",
    angleDeg: 150, // bottom-left
    variant: "observability",
    actions: ["filter audit log", "drill into trace", "read cost rollup"],
    iconPath: (
      <g>
        <circle cx="-3" cy="-3" r="6" fill="none" />
        <line x1="2" y1="2" x2="8" y2="8" />
      </g>
    ),
  },
];

interface Branch {
  id: string;
  tag: string;
  name: string;
  detail: string;
  /** which surface this branches off from */
  fromSurface: "chat" | "observe" | "scenario";
  /** which side: 'left' or 'right' */
  side: "left" | "right";
}

const BRANCHES: Branch[] = [
  {
    id: "jobs",
    tag: "AUTOMATE",
    name: "/jobs",
    detail: "promote a working chat into a cron-driven job",
    fromSurface: "chat",
    side: "left",
  },
  {
    id: "hooks",
    tag: "POLICY",
    name: "/settings/hooks",
    detail: "intercept tool calls · slack on tier-3 · deny in prod",
    fromSurface: "scenario",
    side: "right",
  },
  {
    id: "memory",
    tag: "REMEMBER",
    name: "/memory",
    detail: "teach the agent your environment durably",
    fromSurface: "observe",
    side: "left",
  },
];

const VIEW_W = 1520;
const VIEW_H = 1020;
const CENTER_X = VIEW_W / 2;
const CENTER_Y = 510;
const RADIUS = 280; // distance from center to surface card center
const SURFACE_W = 360;
const SURFACE_H = 200;

/** Convert degrees-from-top (clockwise) to radians-from-east (counter-clockwise) */
function angleRad(deg: number): number {
  return ((deg - 90) * Math.PI) / 180; // ?? actually simpler: use std math math
}

/** Convert position on cycle (0=top, going clockwise) to (x,y) */
function pointOnCycle(angleDeg: number, r: number): [number, number] {
  // angleDeg=-90 means top, 30 means bottom-right, 150 means bottom-left
  const rad = (angleDeg * Math.PI) / 180;
  return [CENTER_X + r * Math.cos(rad), CENTER_Y + r * Math.sin(rad)];
}

export function OperatorDailyLoop() {
  return (
    <div className="dgm-root odl">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="odl-title odl-desc"
      >
        <title id="odl-title">Operator Daily Loop</title>
        <desc id="odl-desc">
          Three-surface daily loop: chat → run scenario → observability → chat.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="odl-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#odl-dot-grid)" />

        <text x="60" y="44" className="title" fontSize="22">
          Operator Daily Loop
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Three primary surfaces form the cycle. Side-branches automate or
          gate parts of the loop without breaking it.
        </text>

        {/* Cyclic loop arrows between surface cards. Control point is
            placed on the cycle going CLOCKWISE between the two surface
            angles, on a smaller-radius circle so the curve bows inward. */}
        {SURFACES.map((s, i) => {
          const next = SURFACES[(i + 1) % SURFACES.length];
          const [fromX, fromY] = pointOnCycle(s.angleDeg, RADIUS - 30);
          const [toX, toY] = pointOnCycle(next.angleDeg, RADIUS - 30);
          // Walk clockwise from s → next: if next.angle < s.angle, add 360
          let nextAngle = next.angleDeg;
          while (nextAngle < s.angleDeg) nextAngle += 360;
          const midAngle = (s.angleDeg + nextAngle) / 2;
          const [cpx, cpy] = pointOnCycle(midAngle, RADIUS - 100);
          return (
            <g key={`loop-${s.id}`}>
              <path
                className="loop-arrow"
                d={`M ${fromX} ${fromY} Q ${cpx} ${cpy} ${toX} ${toY}`}
                markerEnd="url(#dgm-arrow-operator)"
              />
              <text
                className="loop-label"
                x={cpx}
                y={cpy + 4}
                textAnchor="middle"
              >
                {i === 0 ? "dispatch" : i === 1 ? "verify" : "iterate"}
              </text>
            </g>
          );
        })}

        {/* Surface cards */}
        {SURFACES.map((s) => {
          const [cx, cy] = pointOnCycle(s.angleDeg, RADIUS);
          const x = cx - SURFACE_W / 2;
          const y = cy - SURFACE_H / 2;
          return (
            <g key={s.id}>
              <rect
                className={`surface-card ${s.variant ?? "default"}`}
                x={x}
                y={y}
                width={SURFACE_W}
                height={SURFACE_H}
                rx="20"
              />
              <circle
                className="surface-icon-bg"
                cx={x + 36}
                cy={y + 38}
                r="22"
              />
              <g
                className="surface-icon"
                transform={`translate(${x + 36} ${y + 38})`}
              >
                {s.iconPath}
              </g>
              <text
                className="surface-name"
                x={x + 70}
                y={y + 36}
              >
                {s.name}
              </text>
              <text
                className="surface-route"
                x={x + 70}
                y={y + 56}
              >
                {s.route}
              </text>
              <text
                className="surface-detail"
                x={x + 24}
                y={y + 88}
              >
                {s.detail}
              </text>

              {/* Action pills */}
              {s.actions.map((a, ai) => (
                <g key={a} transform={`translate(${x + 24} ${y + 110 + ai * 30})`}>
                  <rect
                    className="surface-action-pill"
                    width={SURFACE_W - 48}
                    height="22"
                    rx="6"
                  />
                  <text className="surface-action-text" x="10" y="15">
                    {a}
                  </text>
                </g>
              ))}
            </g>
          );
        })}

        {/* Side branches */}
        {BRANCHES.map((b, bi) => {
          const surface = SURFACES.find((s) => s.id === b.fromSurface)!;
          const [sx, sy] = pointOnCycle(surface.angleDeg, RADIUS);
          const branchW = 240;
          const branchH = 100;
          const offsetX = b.side === "right" ? 280 : -280 - branchW;
          const branchX = sx + offsetX;
          const branchY = sy - branchH / 2;
          return (
            <g key={b.id}>
              <line
                className="branch-edge"
                x1={
                  b.side === "right"
                    ? sx + SURFACE_W / 2
                    : sx - SURFACE_W / 2
                }
                y1={sy}
                x2={b.side === "right" ? branchX : branchX + branchW}
                y2={sy}
                markerEnd="url(#dgm-arrow-iap)"
              />
              <rect
                className="branch-card"
                x={branchX}
                y={branchY}
                width={branchW}
                height={branchH}
                rx="14"
              />
              <text className="branch-tag" x={branchX + 18} y={branchY + 24}>
                {b.tag}
              </text>
              <text className="branch-name" x={branchX + 18} y={branchY + 50}>
                {b.name}
              </text>
              <text
                className="branch-detail"
                x={branchX + 18}
                y={branchY + 76}
              >
                {b.detail.split(" · ")[0]}
              </text>
              {b.detail.includes("·") && (
                <text
                  className="branch-detail"
                  x={branchX + 18}
                  y={branchY + 92}
                  fontSize="10.5"
                  fill="var(--dgm-text-muted)"
                >
                  {b.detail.split(" · ").slice(1).join(" · ")}
                </text>
              )}
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
            How a typical day flows
          </text>
          <text className="legend-text" x="220" y="4">
            describe a goal in chat → tools dispatch a scenario → check
            observability → refine the prompt or promote it to a job.
            Hooks govern policy; memory makes follow-ups context-aware.
          </text>
        </g>
      </svg>
    </div>
  );
}
