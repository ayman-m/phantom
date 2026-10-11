"use client";

/**
 * Phantom Auth & Trust Boundaries.
 *
 * Concentric trust zones, outermost to innermost:
 *   Operator → Phantom Agent → MCP server → External connectors / Secret store
 *
 * Each boundary crossing is labelled with the auth header it requires.
 * The right column shows the 3-tier tool gating ladder, with the
 * approval queue feeding back into the chat lifecycle.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.atb .zone {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.6;
}
.dgm-root.atb .zone.outer {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-edge-iap);
  stroke-dasharray: 8 7;
}
.dgm-root.atb .zone.agent {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.8;
}
.dgm-root.atb .zone.mcp {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.2;
}
.dgm-root.atb .zone.inner {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-compose);
  stroke-width: 2;
}
.dgm-root.atb .zone-label {
  fill: var(--dgm-text-soft);
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
.dgm-root.atb .auth-header {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-muted);
}
.dgm-root.atb .auth-header.shared {
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.6;
}
.dgm-root.atb .auth-header.operator {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.6;
}
.dgm-root.atb .auth-header.iap {
  stroke: var(--dgm-edge-iap);
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
}
.dgm-root.atb .auth-header.compose {
  stroke: var(--dgm-edge-compose);
  stroke-width: 1.6;
}
.dgm-root.atb .auth-text {
  fill: var(--dgm-text-main);
  font-size: 12px;
  font-weight: 600;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.atb .actor-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-stroke-strong);
  stroke-width: 1.4;
}
.dgm-root.atb .actor-name {
  fill: var(--dgm-text-main);
  font-size: 13px;
  font-weight: 700;
}
.dgm-root.atb .actor-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.atb .tier-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.atb .tier-card.t1 { stroke: var(--dgm-edge-compose); }
.dgm-root.atb .tier-card.t2 { stroke: var(--dgm-edge-shared); stroke-width: 1.8; }
.dgm-root.atb .tier-card.t3 { stroke: var(--dgm-edge-external); stroke-width: 2; }
.dgm-root.atb .tier-num {
  font-size: 22px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.atb .tier-num.t1 { fill: var(--dgm-edge-compose); }
.dgm-root.atb .tier-num.t2 { fill: var(--dgm-edge-shared); }
.dgm-root.atb .tier-num.t3 { fill: var(--dgm-edge-external); }
.dgm-root.atb .tier-name {
  fill: var(--dgm-text-main);
  font-size: 14px;
  font-weight: 700;
}
.dgm-root.atb .tier-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
}
.dgm-root.atb .secret-callout {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.6;
}
`;

const VIEW_W = 1520;
const VIEW_H = 1100;

export function AuthTrustBoundaries() {
  // Concentric ellipses (centered)
  const cx = 540;
  const cy = 560;
  // Outermost (operator zone)
  const outerRx = 480;
  const outerRy = 380;
  const agentRx = 380;
  const agentRy = 290;
  const mcpRx = 280;
  const mcpRy = 200;
  const innerRx = 170;
  const innerRy = 110;

  // Tier cards on right side
  const tierX = 1080;
  const tierY = 200;
  const tierW = 380;
  const tierH = 130;
  const tierGap = 28;

  return (
    <div className="dgm-root atb">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="atb-title atb-desc"
      >
        <title id="atb-title">Auth and trust boundaries</title>
        <desc id="atb-desc">
          Concentric trust zones with auth headers labelling each crossing,
          plus the three-tier approval ladder.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="atb-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#atb-dot-grid)" />

        {/* Header */}
        <text x="60" y="44" className="title" fontSize="22">
          Auth &amp; Trust Boundaries
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Four concentric zones. Each crossing requires a specific auth header.
          Tiered tool gating runs alongside.
        </text>

        {/* ── Concentric zones (outermost first so inner layers stack) ── */}
        <ellipse className="zone outer" cx={cx} cy={cy} rx={outerRx} ry={outerRy} />
        <text
          className="zone-label"
          x={cx - outerRx + 24}
          y={cy - outerRy + 28}
        >
          OPERATOR ZONE · public internet
        </text>

        <ellipse className="zone agent" cx={cx} cy={cy} rx={agentRx} ry={agentRy} />
        <text
          className="zone-label"
          x={cx - agentRx + 22}
          y={cy - agentRy + 26}
          fill="var(--dgm-edge-operator)"
        >
          PHANTOM-AGENT · :3000
        </text>

        <ellipse className="zone mcp" cx={cx} cy={cy} rx={mcpRx} ry={mcpRy} />
        <text
          className="zone-label"
          x={cx - mcpRx + 22}
          y={cy - mcpRy + 24}
          fill="var(--dgm-edge-shared)"
        >
          PHANTOM-MCP
        </text>

        <ellipse className="zone inner" cx={cx} cy={cy} rx={innerRx} ry={innerRy} />
        <text
          className="zone-label"
          x={cx - innerRx + 18}
          y={cy - innerRy + 22}
          fill="var(--dgm-edge-compose)"
        >
          SECRET STORE
        </text>

        {/* Inner zone content — secret store callout */}
        <rect
          x={cx - 140}
          y={cy - 30}
          width="280"
          height="64"
          rx="10"
          className="secret-callout"
        />
        <text
          x={cx}
          y={cy - 8}
          textAnchor="middle"
          className="auth-text"
          fill="var(--dgm-text-main)"
          fontSize="13"
        >
          AES-256-GCM envelopes
        </text>
        <text
          x={cx}
          y={cy + 12}
          textAnchor="middle"
          className="actor-detail"
        >
          KEK from $PHANTOM_SECRET_KEK
        </text>
        <text
          x={cx}
          y={cy + 28}
          textAnchor="middle"
          className="actor-detail"
        >
          plaintext only at call time
        </text>

        {/* ── Boundary auth-header labels ── */}
        {/* Operator → Agent (top of outer→agent gap) */}
        <g>
          <rect
            x={cx - 130}
            y={cy - outerRy - 18}
            width="260"
            height="36"
            rx="10"
            className="auth-header operator"
          />
          <text
            x={cx}
            y={cy - outerRy + 4}
            textAnchor="middle"
            className="auth-text"
            fill="var(--dgm-edge-operator)"
          >
            Authorization: Basic
          </text>
          <text
            x={cx}
            y={cy - outerRy - 26}
            textAnchor="middle"
            className="actor-detail"
            fontSize="10"
          >
            Browser → Agent
          </text>
        </g>

        {/* Tunnel label (left of outer zone, going in) */}
        <g>
          <rect
            x={cx - outerRx - 60}
            y={cy - 18}
            width="200"
            height="36"
            rx="10"
            className="auth-header iap"
          />
          <text
            x={cx - outerRx + 40}
            y={cy + 4}
            textAnchor="middle"
            className="auth-text"
            fill="var(--dgm-edge-iap)"
          >
            SSH → :22
          </text>
          <text
            x={cx - outerRx + 40}
            y={cy - 26}
            textAnchor="middle"
            className="actor-detail"
            fontSize="10"
            fill="var(--dgm-edge-iap)"
          >
            workstation → VM
          </text>
        </g>

        {/* Agent → MCP (top of agent→mcp gap) */}
        <g>
          <rect
            x={cx - 150}
            y={cy - mcpRy - 18 - 20}
            width="300"
            height="36"
            rx="10"
            className="auth-header shared"
          />
          <text
            x={cx}
            y={cy - mcpRy + 4 - 20}
            textAnchor="middle"
            className="auth-text"
            fill="var(--dgm-edge-shared)"
          >
            Authorization: Bearer $MCP_TOKEN
          </text>
          <text
            x={cx}
            y={cy - mcpRy - 26 - 20}
            textAnchor="middle"
            className="actor-detail"
            fontSize="10"
          >
            Agent → MCP (server-side)
          </text>
        </g>

        {/* MCP → secret store (bottom of mcp→inner gap) */}
        <g>
          <rect
            x={cx - 130}
            y={cy + innerRy + 18}
            width="260"
            height="36"
            rx="10"
            className="auth-header compose"
          />
          <text
            x={cx}
            y={cy + innerRy + 40}
            textAnchor="middle"
            className="auth-text"
            fill="var(--dgm-edge-compose)"
          >
            in-process · no wire auth
          </text>
        </g>

        {/* API-key entry — small label + arrow at top-right of operator zone */}
        <g>
          <rect
            x={cx + outerRx - 270}
            y={cy - outerRy - 18}
            width="280"
            height="36"
            rx="10"
            className="auth-header operator"
          />
          <text
            x={cx + outerRx - 130}
            y={cy - outerRy + 4}
            textAnchor="middle"
            className="auth-text"
            fill="var(--dgm-edge-operator)"
          >
            Authorization: Bearer api_key
          </text>
          <text
            x={cx + outerRx - 130}
            y={cy - outerRy - 26}
            textAnchor="middle"
            className="actor-detail"
            fontSize="10"
          >
            API client → /api/v1/*
          </text>
        </g>

        {/* Operator browser actor at top */}
        <g>
          <rect
            x={cx - 130}
            y={cy - outerRy - 100}
            width="260"
            height="62"
            rx="14"
            className="actor-card"
          />
          <text
            x={cx - 110}
            y={cy - outerRy - 76}
            className="actor-name"
          >
            Operator browser
          </text>
          <text
            x={cx - 110}
            y={cy - outerRy - 56}
            className="actor-detail"
          >
            UI auth · 30-min session
          </text>
          <line
            x1={cx}
            y1={cy - outerRy - 38}
            x2={cx}
            y2={cy - outerRy - 18}
            stroke="var(--dgm-edge-operator)"
            strokeWidth="1.6"
            markerEnd="url(#dgm-arrow-operator)"
          />
        </g>

        {/* Operator workstation actor (left, SSH tunnel) */}
        <g>
          <rect
            x={cx - outerRx - 280}
            y={cy - 30}
            width="220"
            height="62"
            rx="14"
            className="actor-card"
            style={{
              stroke: "var(--dgm-edge-iap)",
              strokeDasharray: "4 4",
            }}
          />
          <text
            x={cx - outerRx - 264}
            y={cy - 6}
            className="actor-name"
          >
            Workstation
          </text>
          <text
            x={cx - outerRx - 264}
            y={cy + 14}
            className="actor-detail"
          >
            VM-only · SSH tunnel
          </text>
          <line
            x1={cx - outerRx - 60}
            y1={cy}
            x2={cx - outerRx + 4}
            y2={cy}
            stroke="var(--dgm-edge-iap)"
            strokeWidth="1.6"
            strokeDasharray="4 4"
            markerEnd="url(#dgm-arrow-iap)"
          />
        </g>

        {/* ── Tier ladder (right column) ── */}
        <text x={tierX} y={tierY - 18} className="lane-label" fontSize="11">
          TOOL APPROVAL TIERS
        </text>
        {[
          {
            num: "1",
            cls: "t1",
            name: "Auto-approved",
            detail: "read-only, log-gen, non-destructive",
            example: "xlog.list_workers, xsiam.run_xql",
          },
          {
            num: "2",
            cls: "t2",
            name: "Human approval (default)",
            detail: "config writes, settings changes",
            example: "jobs_create, personality_update",
          },
          {
            num: "3",
            cls: "t3",
            name: "Always human approval",
            detail: "destructive — cannot demote",
            example: "jobs_delete, personality_reset",
          },
        ].map((t, i) => {
          const y = tierY + i * (tierH + tierGap);
          return (
            <g key={t.num}>
              <rect
                className={`tier-card ${t.cls}`}
                x={tierX}
                y={y}
                width={tierW}
                height={tierH}
                rx="14"
              />
              <text className={`tier-num ${t.cls}`} x={tierX + 24} y={y + 36}>
                T{t.num}
              </text>
              <text className="tier-name" x={tierX + 80} y={y + 30}>
                {t.name}
              </text>
              <text className="tier-detail" x={tierX + 80} y={y + 50}>
                {t.detail}
              </text>
              <text
                className="actor-detail"
                x={tierX + 80}
                y={y + 76}
                fontSize="11"
              >
                e.g. {t.example}
              </text>
              {/* Mini approval queue annotation for T2/T3 */}
              {t.num !== "1" && (
                <g>
                  <rect
                    x={tierX + 22}
                    y={y + tierH - 32}
                    width="270"
                    height="22"
                    rx="6"
                    fill="var(--dgm-bg-2)"
                    stroke="var(--dgm-stroke-muted)"
                  />
                  <text
                    x={tierX + 32}
                    y={y + tierH - 16}
                    className="actor-detail"
                    fontSize="10.5"
                  >
                    chat blocks → approval card → operator decides
                  </text>
                </g>
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
            Reading the diagram
          </text>
          <text className="legend-text" x="180" y="4">
            Each ellipse is a trust zone; crossings require the labelled
            auth header. The secret store sits inside MCP — secrets never
            leave the process. Tier ladder runs the approval queue when a
            T2/T3 tool fires.
          </text>
        </g>
      </svg>
    </div>
  );
}
