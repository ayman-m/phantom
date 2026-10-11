"use client";

/**
 * Phantom Persistent Stores & Audit Trail.
 *
 * Hourglass composition: 8 SQLite stores at the top all converge on a
 * hero `audit_log` row in the middle, which fans out to 6 derivative
 * observability surfaces at the bottom. The visual argument: every
 * operator-visible surface is a derived view over one append-only
 * audit table.
 *
 * No animations. Pure SVG + CSS, theme-aware via the shared
 * _diagram-theme module.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.psa .store-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.psa .audit-hero-bg {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.4;
}
.dgm-root.psa .audit-hero-glow {
  fill: var(--dgm-edge-shared);
  opacity: 0.10;
}
.dgm-root.psa .surface-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.4;
}
.dgm-root.psa .store-icon-badge {
  fill: var(--dgm-badge-bg);
  stroke: var(--dgm-badge-stroke);
  stroke-width: 1;
}
.dgm-root.psa .store-icon {
  fill: none;
  stroke: var(--dgm-text-main);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dgm-root.psa .store-name {
  font-size: 13px;
  font-weight: 700;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.psa .store-detail {
  font-size: 11px;
  fill: var(--dgm-text-soft);
}
.dgm-root.psa .audit-title {
  font-size: 22px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
  letter-spacing: -0.01em;
}
.dgm-root.psa .audit-tag {
  fill: var(--dgm-edge-shared);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
.dgm-root.psa .audit-col {
  font-size: 11.5px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.psa .audit-col-key {
  font-size: 11.5px;
  fill: var(--dgm-edge-shared);
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.psa .surface-name {
  font-size: 13px;
  font-weight: 700;
  fill: var(--dgm-text-main);
}
.dgm-root.psa .surface-detail {
  font-size: 10.5px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.psa .converge-edge {
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.2;
  fill: none;
}
.dgm-root.psa .fanout-edge {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.4;
  fill: none;
}
`;

interface Store {
  id: string;
  /** display name (rendered monospace) */
  name: string;
  detail: string;
  /** lucide-style line icon paths (within a 24x24 viewBox, centred at 12,12) */
  icon: React.ReactNode;
}

const STORES: Store[] = [
  {
    id: "sessions",
    name: "sessions.db",
    detail: "chats + messages · 30-day TTL",
    icon: (
      <g>
        <rect x="-9" y="-7" width="18" height="14" rx="2" fill="none" />
        <line x1="-9" y1="-3" x2="9" y2="-3" />
        <circle cx="-5" cy="-5" r="0.5" />
      </g>
    ),
  },
  {
    id: "memory",
    name: "memory.db",
    detail: "vec + FTS5 · MMR + decay",
    icon: (
      <g>
        <ellipse cx="0" cy="-5" rx="8" ry="3" fill="none" />
        <path d="M -8 -5 V 5 a 8 3 0 0 0 16 0 V -5" fill="none" />
        <path d="M -8 0 a 8 3 0 0 0 16 0" fill="none" />
      </g>
    ),
  },
  {
    id: "secrets",
    name: "secret_store.db",
    detail: "AES-256-GCM envelopes",
    icon: (
      <g>
        <rect x="-7" y="-2" width="14" height="10" rx="2" fill="none" />
        <path d="M -4 -2 V -5 a 4 4 0 0 1 8 0 V -2" fill="none" />
      </g>
    ),
  },
  {
    id: "jobs",
    name: "jobs.db",
    detail: "cron · runs · manifest+operator",
    icon: (
      <g>
        <circle cx="0" cy="0" r="8" fill="none" />
        <line x1="0" y1="0" x2="0" y2="-5" />
        <line x1="0" y1="0" x2="4" y2="2" />
      </g>
    ),
  },
  {
    id: "tasks",
    name: "tasks.db",
    detail: "pending→running→done|fail",
    icon: (
      <g>
        <rect x="-8" y="-7" width="16" height="14" rx="2" fill="none" />
        <polyline points="-4,-1 -1,2 4,-3" fill="none" />
      </g>
    ),
  },
  {
    id: "hooks",
    name: "hooks.db",
    detail: "policy · 6 fire-sites",
    icon: (
      <g>
        <path d="M -7 -7 V 0 a 7 7 0 0 0 14 0 V -7" fill="none" />
        <line x1="-7" y1="-7" x2="-3" y2="-7" />
      </g>
    ),
  },
  {
    id: "agents",
    name: "agent_definitions.db",
    detail: "built-in · plugin · operator",
    icon: (
      <g>
        <circle cx="-4" cy="-3" r="3" fill="none" />
        <path d="M -10 7 a 6 5 0 0 1 12 0" fill="none" />
        <circle cx="6" cy="-1" r="2" fill="none" />
        <path d="M 2 7 a 4 3 0 0 1 8 0" fill="none" />
      </g>
    ),
  },
  {
    id: "connector_state",
    name: "connector_state.db",
    detail: "5-state machine per inst.",
    icon: (
      <g>
        <rect x="-8" y="-3" width="6" height="6" rx="1" fill="none" />
        <rect x="2" y="-3" width="6" height="6" rx="1" fill="none" />
        <line x1="-2" y1="0" x2="2" y2="0" />
        <line x1="0" y1="3" x2="0" y2="7" />
      </g>
    ),
  },
];

interface Surface {
  id: string;
  name: string;
  detail: string;
  icon: React.ReactNode;
}

const SURFACES: Surface[] = [
  {
    id: "events",
    name: "/events",
    detail: "paginated audit query",
    icon: (
      <g>
        <line x1="-7" y1="-5" x2="7" y2="-5" />
        <line x1="-7" y1="0" x2="7" y2="0" />
        <line x1="-7" y1="5" x2="3" y2="5" />
      </g>
    ),
  },
  {
    id: "traces",
    name: "/traces",
    detail: "span tree per turn",
    icon: (
      <g>
        <line x1="-7" y1="-6" x2="-7" y2="6" />
        <line x1="-7" y1="-3" x2="2" y2="-3" />
        <line x1="-7" y1="0" x2="6" y2="0" />
        <line x1="-7" y1="3" x2="3" y2="3" />
      </g>
    ),
  },
  {
    id: "metrics",
    name: "/metrics",
    detail: "Prometheus histograms",
    icon: (
      <g>
        <polyline points="-8,5 -4,1 0,3 4,-3 8,-1" fill="none" />
        <line x1="-8" y1="6" x2="8" y2="6" />
      </g>
    ),
  },
  {
    id: "cost",
    name: "/cost",
    detail: "chat_turn_cost rollup",
    icon: (
      <g>
        <circle cx="0" cy="0" r="7" fill="none" />
        <text
          x="0"
          y="3.5"
          textAnchor="middle"
          fontSize="9"
          fill="currentColor"
          stroke="none"
          fontWeight="700"
        >
          $
        </text>
      </g>
    ),
  },
  {
    id: "notifications",
    name: "/notifications",
    detail: "operator-visible subset",
    icon: (
      <g>
        <path d="M -6 -2 v 6 h 12 v -6 a 6 6 0 0 0 -12 0 z" fill="none" />
        <path d="M -2 4 a 2 2 0 0 0 4 0" fill="none" />
      </g>
    ),
  },
  {
    id: "pipeline",
    name: "/pipeline",
    detail: "edge pulses from audit",
    icon: (
      <g>
        <circle cx="-5" cy="-3" r="2" fill="none" />
        <circle cx="5" cy="-3" r="2" fill="none" />
        <circle cx="0" cy="5" r="2" fill="none" />
        <line x1="-3" y1="-2" x2="-1" y2="3" />
        <line x1="3" y1="-2" x2="1" y2="3" />
      </g>
    ),
  },
];

// ── Layout constants ─────────────────────────────────────────────
const VIEW_W = 1520;
const VIEW_H = 1100;

// Stores grid: 4 cols × 2 rows
const STORES_TOP = 100;
const STORE_W = 280;
const STORE_H = 80;
const STORES_COL_GAP = 40;
const STORES_ROW_GAP = 22;
const STORES_GRID_W = 4 * STORE_W + 3 * STORES_COL_GAP;
const STORES_LEFT = (VIEW_W - STORES_GRID_W) / 2;

// Audit hero band
const AUDIT_W = 980;
const AUDIT_H = 160;
const AUDIT_LEFT = (VIEW_W - AUDIT_W) / 2;
const AUDIT_TOP = 480;

// Surfaces row: 6 cols
const SURFACE_W = 200;
const SURFACE_H = 80;
const SURFACES_TOP = 760;
const SURFACES_GAP = 22;
const SURFACES_GRID_W = 6 * SURFACE_W + 5 * SURFACES_GAP;
const SURFACES_LEFT = (VIEW_W - SURFACES_GRID_W) / 2;


function storePos(idx: number): [number, number] {
  const col = idx % 4;
  const row = Math.floor(idx / 4);
  return [
    STORES_LEFT + col * (STORE_W + STORES_COL_GAP),
    STORES_TOP + row * (STORE_H + STORES_ROW_GAP),
  ];
}

function surfacePos(idx: number): [number, number] {
  return [
    SURFACES_LEFT + idx * (SURFACE_W + SURFACES_GAP),
    SURFACES_TOP,
  ];
}

export function PersistentStores() {
  const auditCx = AUDIT_LEFT + AUDIT_W / 2;
  const auditTopY = AUDIT_TOP;
  const auditBottomY = AUDIT_TOP + AUDIT_H;

  return (
    <div className="dgm-root psa">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="psa-title psa-desc"
      >
        <title id="psa-title">Persistent stores and audit trail</title>
        <desc id="psa-desc">
          Eight SQLite stores converge on a hero audit log, which fans out to
          six observability surfaces.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="psa-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#psa-dot-grid)" />

        {/* Header */}
        <text x="60" y="44" className="title" fontSize="22">
          Persistent Stores &amp; Audit Trail
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          8 SQLite stores feed one append-only audit log; 6 observability
          surfaces are derived views over it.
        </text>

        {/* Section labels */}
        <text x="60" y={STORES_TOP - 8} className="lane-label" fontSize="11">
          STORES
        </text>
        <text
          x="60"
          y={SURFACES_TOP - 14}
          className="lane-label"
          fontSize="11"
        >
          DERIVED OBSERVABILITY SURFACES
        </text>

        {/* Convergence edges: each store's bottom-center → audit hero top */}
        {STORES.map((s, i) => {
          const [sx, sy] = storePos(i);
          const fromX = sx + STORE_W / 2;
          const fromY = sy + STORE_H;
          const toX = auditCx + (i - 3.5) * 36; // splay landing points
          const toY = auditTopY;
          const midY = (fromY + toY) / 2;
          return (
            <path
              key={`conv-${s.id}`}
              className="converge-edge"
              d={`M ${fromX} ${fromY} C ${fromX} ${midY}, ${toX} ${midY}, ${toX} ${toY}`}
            />
          );
        })}

        {/* Stores */}
        {STORES.map((s, i) => {
          const [x, y] = storePos(i);
          return (
            <g key={s.id}>
              <rect
                className="store-card"
                x={x}
                y={y}
                width={STORE_W}
                height={STORE_H}
                rx="14"
              />
              <circle
                className="store-icon-badge"
                cx={x + 28}
                cy={y + STORE_H / 2}
                r="18"
              />
              <g
                className="store-icon"
                transform={`translate(${x + 28} ${y + STORE_H / 2})`}
              >
                {s.icon}
              </g>
              <text className="store-name" x={x + 56} y={y + 30}>
                {s.name}
              </text>
              <text className="store-detail" x={x + 56} y={y + 52}>
                {s.detail}
              </text>
            </g>
          );
        })}

        {/* Audit hero band */}
        <rect
          className="audit-hero-glow"
          x={AUDIT_LEFT - 10}
          y={AUDIT_TOP - 10}
          width={AUDIT_W + 20}
          height={AUDIT_H + 20}
          rx="20"
        />
        <rect
          className="audit-hero-bg"
          x={AUDIT_LEFT}
          y={AUDIT_TOP}
          width={AUDIT_W}
          height={AUDIT_H}
          rx="18"
        />
        <text
          className="audit-tag"
          x={AUDIT_LEFT + 28}
          y={AUDIT_TOP + 30}
        >
          UNIVERSAL APPEND-ONLY SURFACE
        </text>
        <text
          className="audit-title"
          x={AUDIT_LEFT + 28}
          y={AUDIT_TOP + 60}
        >
          audit_log
        </text>
        {/* Schema preview row */}
        {[
          { col: "id", note: "uuid4 PK", x: 28 },
          { col: "ts", note: "ISO8601 UTC", x: 116 },
          { col: "actor", note: "user / system", x: 226 },
          { col: "action", note: "tool_call · hook_*", x: 360 },
          { col: "target", note: "tool · session", x: 530 },
          { col: "status", note: "success | error", x: 660 },
          { col: "duration_ms", note: "nullable", x: 800 },
        ].map(({ col, note, x }) => (
          <g key={col} transform={`translate(${AUDIT_LEFT + x} ${AUDIT_TOP + 92})`}>
            <text className="audit-col-key" x="0" y="0">
              {col}
            </text>
            <text className="audit-col" x="0" y="20">
              {note}
            </text>
          </g>
        ))}
        {/* metadata_json row */}
        <text
          className="audit-col-key"
          x={AUDIT_LEFT + 28}
          y={AUDIT_TOP + 144}
        >
          metadata_json
        </text>
        <text
          className="audit-col"
          x={AUDIT_LEFT + 28 + 110}
          y={AUDIT_TOP + 144}
        >
          action-specific JSON · NEVER stores secret values
        </text>

        {/* Fan-out edges: audit hero bottom → each surface top */}
        {SURFACES.map((s, i) => {
          const [sx, sy] = surfacePos(i);
          const toX = sx + SURFACE_W / 2;
          const toY = sy;
          const fromX = auditCx + (i - 2.5) * 60;
          const fromY = auditBottomY;
          const midY = (fromY + toY) / 2;
          return (
            <path
              key={`fan-${s.id}`}
              className="fanout-edge"
              d={`M ${fromX} ${fromY} C ${fromX} ${midY}, ${toX} ${midY}, ${toX} ${toY}`}
              markerEnd="url(#dgm-arrow-operator)"
            />
          );
        })}

        {/* Surfaces */}
        {SURFACES.map((s, i) => {
          const [x, y] = surfacePos(i);
          return (
            <g key={s.id}>
              <rect
                className="surface-card"
                x={x}
                y={y}
                width={SURFACE_W}
                height={SURFACE_H}
                rx="14"
              />
              <circle
                className="store-icon-badge"
                cx={x + 28}
                cy={y + SURFACE_H / 2}
                r="18"
              />
              <g
                className="store-icon"
                transform={`translate(${x + 28} ${y + SURFACE_H / 2})`}
              >
                {s.icon}
              </g>
              <text className="surface-name" x={x + 56} y={y + 30}>
                {s.name}
              </text>
              <text className="surface-detail" x={x + 56} y={y + 52}>
                {s.detail}
              </text>
            </g>
          );
        })}

        {/* Footnote */}
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
            Why this shape?
          </text>
          <text className="legend-text" x="160" y="4">
            One source of truth for queries means notifications, traces,
            metrics, cost, and the pipeline graph never go stale —
            adding a new audit family adds the new surface for free.
          </text>
        </g>
      </svg>
    </div>
  );
}
