"use client";

/**
 * Phantom auth topology — static component graph.
 *
 * Companion to auth-flows.tsx. The flow diagrams there show TEMPORAL
 * interactions for three operator journeys (login, change-password,
 * CLI reset); this diagram shows the STATIC component layout the
 * flows traverse — who lives in which trust tier, what protocol
 * crosses each boundary, where the canonical storage sits, and how
 * the audit + CLI side-channels attach.
 *
 * Visual argument:
 *   • Four tiers stacked vertically: User → Edge → Auth Service →
 *     Storage. Each tier is a trust band.
 *   • SecretStore + auth_sessions.db are the only two persisted-state
 *     stores — drawn extra-prominent at the bottom.
 *   • Audit observer sits to the right, receiving events from every
 *     auth action in the service tier.
 *   • CLI reset is shown as a dashed bypass on the left, skipping
 *     the browser + Edge tiers entirely (trust boundary = shell
 *     access on the host).
 *
 * Why static (no animation): topology is a contract, not a journey.
 * Animation would imply a directionality the diagram doesn't have —
 * components co-exist, they don't take turns. The 3 flow diagrams in
 * auth-flows.tsx already cover the temporal axis.
 *
 * No legacy fallback paths are shown (there are none).
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

// ─────────────────────────────────────────────────────────────────
// Geometry
// ─────────────────────────────────────────────────────────────────

const VIEW_W = 1180;
const VIEW_H = 660;

// Tier vertical positions (band centerline y).
const TIER = {
  user: 70,
  edge: 200,
  service: 340,
  storage: 510,
};

const TIER_BAND_H = 110;
const STORAGE_BAND_H = 140;

const TIER_LABEL_X = 32; // tier band labels sit on the far left
const COLUMN_CENTER = 600; // diagram's central spine

const BOX = {
  w: 200,
  h: 84,
  // SecretStore + auth_sessions.db get hero treatment in the storage tier.
  storeW: 280,
  storeH: 110,
};

// Audit log lives in the right gutter, vertically spanning service + storage.
const AUDIT = {
  x: 1000,
  y: 340,
  w: 150,
  h: 200,
};

// CLI bypass path on the left, spanning user → service tiers.
const CLI = {
  x: 30,
  y: 200,
  w: 200,
  h: 130,
};

// ─────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.auth-topology .tier-band {
  fill: var(--dgm-panel);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
  stroke-dasharray: 4 5;
  rx: 14;
}
.dgm-root.auth-topology .tier-label {
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  fill: var(--dgm-text-muted);
}
.dgm-root.auth-topology .tier-sub {
  font-size: 10px;
  fill: var(--dgm-text-muted);
  font-style: italic;
}

.dgm-root.auth-topology .node-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
  rx: 12;
}
.dgm-root.auth-topology .node-card.user { stroke: var(--dgm-edge-operator); }
.dgm-root.auth-topology .node-card.edge { stroke: var(--dgm-state-info); }
.dgm-root.auth-topology .node-card.service { stroke: var(--dgm-edge-compose); }
.dgm-root.auth-topology .node-card.store {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.4;
}
.dgm-root.auth-topology .node-card.audit {
  fill: var(--dgm-sink-fill);
  stroke: var(--dgm-text-muted);
  stroke-dasharray: 5 4;
}
.dgm-root.auth-topology .node-card.cli {
  fill: var(--dgm-external-fill);
  stroke: var(--dgm-edge-iap);
  stroke-dasharray: 8 6;
}

.dgm-root.auth-topology .node-title {
  font-size: 13.5px;
  font-weight: 760;
  fill: var(--dgm-text-main);
}
.dgm-root.auth-topology .store-title {
  font-size: 15px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  letter-spacing: 0.02em;
}
.dgm-root.auth-topology .node-sub {
  font-size: 10.5px;
  fill: var(--dgm-code);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-topology .node-detail {
  font-size: 10px;
  fill: var(--dgm-text-soft);
}

.dgm-root.auth-topology .edge-line {
  fill: none;
  stroke: var(--dgm-stroke-strong);
  stroke-width: 1.6;
}
.dgm-root.auth-topology .edge-line.cli {
  stroke: var(--dgm-edge-iap);
  stroke-dasharray: 8 6;
}
.dgm-root.auth-topology .edge-line.audit {
  stroke: var(--dgm-text-muted);
  stroke-dasharray: 3 4;
}
.dgm-root.auth-topology .edge-line.store {
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.9;
}

.dgm-root.auth-topology .edge-label-bg {
  fill: var(--dgm-label-bg);
  stroke: var(--dgm-label-border);
  stroke-width: 0.75;
  rx: 4;
}
.dgm-root.auth-topology .edge-label {
  font-size: 10px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}

.dgm-root.auth-topology .boundary-tag {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  fill: var(--dgm-state-warn);
}

.dgm-root.auth-topology .legend-key {
  font-size: 9.5px;
  fill: var(--dgm-text-muted);
}
`;

// ─────────────────────────────────────────────────────────────────
// Helpers — node + edge rendering
// ─────────────────────────────────────────────────────────────────

interface NodeProps {
  x: number;
  y: number;
  w?: number;
  h?: number;
  variant: "user" | "edge" | "service" | "store" | "audit" | "cli";
  title: string;
  sub?: string;
  detail?: string;
}

function TopologyNode({
  x,
  y,
  w = BOX.w,
  h = BOX.h,
  variant,
  title,
  sub,
  detail,
}: NodeProps) {
  const cx = x + w / 2;
  const titleY = y + 26;
  const subY = sub ? y + 46 : 0;
  const detailY = detail ? (sub ? y + 65 : y + 48) : 0;
  return (
    <g>
      <rect
        className={`node-card ${variant}`}
        x={x}
        y={y}
        width={w}
        height={h}
      />
      <text
        className={variant === "store" ? "store-title" : "node-title"}
        x={cx}
        y={titleY}
        textAnchor="middle"
      >
        {title}
      </text>
      {sub && (
        <text
          className="node-sub"
          x={cx}
          y={subY}
          textAnchor="middle"
        >
          {sub}
        </text>
      )}
      {detail && (
        <text
          className="node-detail"
          x={cx}
          y={detailY}
          textAnchor="middle"
        >
          {detail}
        </text>
      )}
    </g>
  );
}

interface EdgeLabelProps {
  x: number;
  y: number;
  text: string;
  /** Approximate label width. The bg pill sizes to this; pick generously. */
  w?: number;
}

function EdgeLabel({ x, y, text, w = 220 }: EdgeLabelProps) {
  return (
    <g>
      <rect
        className="edge-label-bg"
        x={x - w / 2}
        y={y - 9}
        width={w}
        height={18}
      />
      <text
        className="edge-label"
        x={x}
        y={y + 4}
        textAnchor="middle"
      >
        {text}
      </text>
    </g>
  );
}

interface EdgeProps {
  from: { x: number; y: number };
  to: { x: number; y: number };
  variant?: "default" | "cli" | "audit" | "store";
  label?: string;
  labelOffsetY?: number;
  labelW?: number;
}

function TopologyEdge({
  from,
  to,
  variant = "default",
  label,
  labelOffsetY = 0,
  labelW,
}: EdgeProps) {
  // Straight orthogonal connectors; topology is about structure, not
  // motion — Bezier curves would add noise.
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const path = `M ${from.x},${from.y} L ${to.x},${to.y}`;
  const className = `edge-line${variant !== "default" ? ` ${variant}` : ""}`;
  // Marker color matches the visual variant. The IDs are exported by
  // DiagramMarkers in _diagram-theme.tsx — keep these in sync.
  const markerId =
    variant === "cli"
      ? "dgm-arrow-iap"
      : variant === "audit"
        ? "dgm-arrow-muted"
        : variant === "store"
          ? "dgm-arrow-shared"
          : "dgm-arrow-operator";
  return (
    <g>
      <path
        d={path}
        className={className}
        markerEnd={`url(#${markerId})`}
      />
      {label && (
        <EdgeLabel
          x={midX}
          y={midY + labelOffsetY}
          text={label}
          w={labelW}
        />
      )}
    </g>
  );
}

// ─────────────────────────────────────────────────────────────────
// Main diagram
// ─────────────────────────────────────────────────────────────────

export function AuthTopology() {
  // Pre-compute box positions for the canonical 4-tier layout.
  //
  // User tier: one box centered.
  // Edge tier: two boxes (tls-proxy + Next.js routes) side by side.
  // Service tier: three boxes (HTTP routes + orchestrator + crypto).
  // Storage tier: two HERO boxes (SecretStore + auth_sessions.db).

  // User tier
  const userBox = {
    x: COLUMN_CENTER - BOX.w / 2,
    y: TIER.user - BOX.h / 2,
  };

  // Edge tier — two boxes, evenly spaced around the centerline
  const edgeGap = 40;
  const edge1 = {
    x: COLUMN_CENTER - BOX.w - edgeGap / 2,
    y: TIER.edge - BOX.h / 2,
  };
  const edge2 = {
    x: COLUMN_CENTER + edgeGap / 2,
    y: TIER.edge - BOX.h / 2,
  };

  // Service tier — three boxes, evenly spaced
  const svcW = 195;
  const svcGap = 22;
  const svcRowWidth = svcW * 3 + svcGap * 2;
  const svcStart = COLUMN_CENTER - svcRowWidth / 2;
  const svc1 = { x: svcStart, y: TIER.service - BOX.h / 2 };
  const svc2 = {
    x: svcStart + svcW + svcGap,
    y: TIER.service - BOX.h / 2,
  };
  const svc3 = {
    x: svcStart + (svcW + svcGap) * 2,
    y: TIER.service - BOX.h / 2,
  };

  // Storage tier — two hero boxes
  const storeGap = 70;
  const store1 = {
    x: COLUMN_CENTER - BOX.storeW - storeGap / 2,
    y: TIER.storage - BOX.storeH / 2,
  };
  const store2 = {
    x: COLUMN_CENTER + storeGap / 2,
    y: TIER.storage - BOX.storeH / 2,
  };

  return (
    <figure className="my-8">
      <style>{STYLES}</style>
      <svg
        className="dgm-root auth-topology w-full"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Phantom authentication topology: User → Edge (tls-proxy + Next.js) → Auth Service (MCP) → Storage (SecretStore + auth_sessions.db), with audit log observing on the right and CLI reset bypass on the left."
      >
        <DiagramMarkers />

        {/* ── Tier bands (background) ─────────────────────────────── */}
        <rect
          className="tier-band"
          x={140}
          y={TIER.user - TIER_BAND_H / 2}
          width={VIEW_W - 280}
          height={TIER_BAND_H}
        />
        <rect
          className="tier-band"
          x={140}
          y={TIER.edge - TIER_BAND_H / 2}
          width={VIEW_W - 280}
          height={TIER_BAND_H}
        />
        <rect
          className="tier-band"
          x={140}
          y={TIER.service - TIER_BAND_H / 2}
          width={VIEW_W - 280}
          height={TIER_BAND_H}
        />
        <rect
          className="tier-band"
          x={140}
          y={TIER.storage - STORAGE_BAND_H / 2}
          width={VIEW_W - 280}
          height={STORAGE_BAND_H}
        />

        {/* ── Tier labels ─────────────────────────────────────────── */}
        <text
          className="tier-label"
          x={TIER_LABEL_X + 130}
          y={TIER.user - TIER_BAND_H / 2 + 14}
        >
          USER
        </text>
        <text
          className="tier-sub"
          x={TIER_LABEL_X + 130}
          y={TIER.user - TIER_BAND_H / 2 + 28}
        >
          untrusted
        </text>

        <text
          className="tier-label"
          x={TIER_LABEL_X + 130}
          y={TIER.edge - TIER_BAND_H / 2 + 14}
        >
          EDGE
        </text>
        <text
          className="tier-sub"
          x={TIER_LABEL_X + 130}
          y={TIER.edge - TIER_BAND_H / 2 + 28}
        >
          tls + cookie auth
        </text>

        <text
          className="tier-label"
          x={TIER_LABEL_X + 130}
          y={TIER.service - TIER_BAND_H / 2 + 14}
        >
          AUTH SERVICE
        </text>
        <text
          className="tier-sub"
          x={TIER_LABEL_X + 130}
          y={TIER.service - TIER_BAND_H / 2 + 28}
        >
          loopback + bearer
        </text>

        <text
          className="tier-label"
          x={TIER_LABEL_X + 130}
          y={TIER.storage - STORAGE_BAND_H / 2 + 14}
        >
          STORAGE
        </text>
        <text
          className="tier-sub"
          x={TIER_LABEL_X + 130}
          y={TIER.storage - STORAGE_BAND_H / 2 + 28}
        >
          canonical · single source of truth
        </text>

        {/* ── Trust boundary markers ──────────────────────────────── */}
        <text
          className="boundary-tag"
          x={VIEW_W - 150}
          y={TIER.edge - TIER_BAND_H / 2 - 4}
          textAnchor="end"
        >
          ↑ network boundary ↑
        </text>
        <text
          className="boundary-tag"
          x={VIEW_W - 150}
          y={TIER.service - TIER_BAND_H / 2 - 4}
          textAnchor="end"
        >
          ↑ process boundary (in-container) ↑
        </text>

        {/* ── Nodes ───────────────────────────────────────────────── */}
        {/* User tier */}
        <TopologyNode
          {...userBox}
          variant="user"
          title="Operator browser"
          sub="https://host:3000"
          detail="cookie: phantom_session"
        />

        {/* Edge tier */}
        <TopologyNode
          {...edge1}
          variant="edge"
          title="tls-proxy.js"
          sub="3000 → 3001"
          detail="TLS termination"
        />
        <TopologyNode
          {...edge2}
          variant="edge"
          title="Next.js /api/auth/*"
          sub="login · logout · status"
          detail="change-password · session-lifetime"
        />

        {/* Service tier */}
        <TopologyNode
          {...svc1}
          w={svcW}
          variant="service"
          title="api/ui_auth.py"
          sub="HTTP routes"
          detail="MCP /api/v1/ui/auth/*"
        />
        <TopologyNode
          {...svc2}
          w={svcW}
          variant="service"
          title="usecase/auth_store.py"
          sub="orchestrator"
          detail="seed · session · flag"
        />
        <TopologyNode
          {...svc3}
          w={svcW}
          variant="service"
          title="usecase/ui_auth.py"
          sub="crypto envelope"
          detail="PBKDF2 600k iters"
        />

        {/* Storage tier (hero) */}
        <TopologyNode
          {...store1}
          w={BOX.storeW}
          h={BOX.storeH}
          variant="store"
          title="SecretStore"
          sub="/ui/auth/admin/*"
          detail="password_hash + credentials_changed"
        />
        <TopologyNode
          {...store2}
          w={BOX.storeW}
          h={BOX.storeH}
          variant="store"
          title="auth_sessions.db"
          sub="SQLite"
          detail="token_hash · expires_at · revoked_at"
        />

        {/* Audit observer (right gutter) */}
        <TopologyNode
          x={AUDIT.x}
          y={AUDIT.y}
          w={AUDIT.w}
          h={AUDIT.h}
          variant="audit"
          title="Audit log"
          sub="audit_events"
          detail="every action ↓"
        />
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 90}
          textAnchor="middle"
        >
          login_success
        </text>
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 106}
          textAnchor="middle"
        >
          login_failed
        </text>
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 122}
          textAnchor="middle"
        >
          password_changed_ui
        </text>
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 138}
          textAnchor="middle"
        >
          password_changed_cli
        </text>
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 154}
          textAnchor="middle"
        >
          logout · session_revoked
        </text>
        <text
          className="node-detail"
          x={AUDIT.x + AUDIT.w / 2}
          y={AUDIT.y + 170}
          textAnchor="middle"
        >
          secret_read · secret_write
        </text>

        {/* CLI reset bypass (left gutter) */}
        <TopologyNode
          x={CLI.x}
          y={CLI.y}
          w={CLI.w}
          h={CLI.h}
          variant="cli"
          title="Host shell"
          sub="docker exec phantom_agent"
          detail="reset-admin.mjs"
        />
        <text
          className="node-detail"
          x={CLI.x + CLI.w / 2}
          y={CLI.y + 86}
          textAnchor="middle"
        >
          reads MCP_TOKEN
        </text>
        <text
          className="node-detail"
          x={CLI.x + CLI.w / 2}
          y={CLI.y + 102}
          textAnchor="middle"
        >
          from /proc/1/environ
        </text>
        <text
          className="node-detail"
          x={CLI.x + CLI.w / 2}
          y={CLI.y + 118}
          textAnchor="middle"
        >
          trust = host root
        </text>

        {/* ── Inter-tier edges ────────────────────────────────────── */}
        {/* User → Edge.next.js route box */}
        <TopologyEdge
          from={{ x: COLUMN_CENTER, y: userBox.y + BOX.h }}
          to={{ x: edge2.x + BOX.w / 2, y: edge1.y }}
          label="HTTPS + phantom_session cookie"
          labelOffsetY={-2}
          labelW={260}
        />
        {/* User → tls-proxy (parallel arrow showing TLS-terminating) */}
        <TopologyEdge
          from={{ x: COLUMN_CENTER - 60, y: userBox.y + BOX.h }}
          to={{ x: edge1.x + BOX.w / 2, y: edge1.y }}
        />

        {/* Edge → Service: Next.js → api/ui_auth.py (route handlers proxy) */}
        <TopologyEdge
          from={{ x: edge2.x + BOX.w / 2, y: edge2.y + BOX.h }}
          to={{ x: svc1.x + svcW / 2, y: svc1.y }}
          label="loopback HTTPS + bearer MCP_TOKEN"
          labelOffsetY={-2}
          labelW={280}
        />

        {/* Service internal: api → orchestrator → crypto (horizontal chain) */}
        <TopologyEdge
          from={{ x: svc1.x + svcW, y: TIER.service }}
          to={{ x: svc2.x, y: TIER.service }}
        />
        <TopologyEdge
          from={{ x: svc2.x + svcW, y: TIER.service }}
          to={{ x: svc3.x, y: TIER.service }}
        />

        {/* Service → Storage: orchestrator writes to BOTH stores */}
        <TopologyEdge
          from={{ x: svc2.x + svcW / 2 - 30, y: svc2.y + BOX.h }}
          to={{ x: store1.x + BOX.storeW / 2, y: store1.y }}
          variant="store"
          label="AES-GCM at rest"
          labelOffsetY={-2}
          labelW={150}
        />
        <TopologyEdge
          from={{ x: svc2.x + svcW / 2 + 30, y: svc2.y + BOX.h }}
          to={{ x: store2.x + BOX.storeW / 2, y: store2.y }}
          variant="store"
          label="SHA-256 token hash"
          labelOffsetY={-2}
          labelW={170}
        />

        {/* Service → Audit: dotted line from service tier to audit observer */}
        <TopologyEdge
          from={{ x: svc3.x + svcW, y: TIER.service - 30 }}
          to={{ x: AUDIT.x, y: AUDIT.y + 40 }}
          variant="audit"
        />

        {/* CLI bypass: shell node → service (skips browser + Next.js) */}
        <TopologyEdge
          from={{ x: CLI.x + CLI.w, y: CLI.y + CLI.h / 2 }}
          to={{ x: svc1.x, y: svc1.y + BOX.h / 2 }}
          variant="cli"
          label="POST /admin_reset (bypass)"
          labelOffsetY={-2}
          labelW={240}
        />

        {/* ── Legend ──────────────────────────────────────────────── */}
        <g transform={`translate(140, ${VIEW_H - 28})`}>
          <text className="legend-key" x={0} y={0}>
            Solid line = normal path
          </text>
          <text className="legend-key" x={170} y={0}>
            Dashed-amber = CLI bypass (out-of-band)
          </text>
          <text className="legend-key" x={420} y={0}>
            Dotted = audit observation (write-only)
          </text>
          <text className="legend-key" x={680} y={0}>
            Heavy-amber = storage write
          </text>
        </g>
      </svg>
      <figcaption className="text-xs text-on-surface-variant/70 italic text-center mt-2">
        Authentication topology — 4 trust tiers, 2 canonical
        stores, audit-observed, with the CLI reset path shown as an
        explicit out-of-band bypass for the forgot-password case.
      </figcaption>
    </figure>
  );
}
