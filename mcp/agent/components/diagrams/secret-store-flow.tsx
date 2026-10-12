"use client";

/**
 * Phantom SecretStore Flow.
 *
 * Visual argument: the SecretStore is the single encrypted-at-rest
 * source of truth for every operator credential the platform handles.
 * Write surfaces converge on it (top half) and read consumers fan out
 * from it (bottom half), all going through the same AES-256-GCM
 * envelope (the UI password is stored as a PBKDF2 hash inside it).
 *
 * Highlights three operator-relevant points:
 *
 *  1. First boot needs no operator input. The installer writes
 *     /opt/phantom/.env (including PHANTOM_DEFAULT_ADMIN_PASSWORD),
 *     entrypoint.sh seeds the admin password hash into the store, the
 *     operator logs in and rotates it at /profile, then adds provider
 *     credentials at /providers and connector instance credentials at
 *     /connectors. Every edit is surgical and surface-specific; there
 *     are no merge-vs-replace semantics.
 *
 *  2. The SecretStore is a file tree under /app/data/secrets/ on the
 *     phantom_mcp_data volume, so the encrypted files survive
 *     `docker compose down + up` with a new image (the canonical
 *     upgrade flow). The AES-256-GCM key is PHANTOM_SECRET_KEK, pinned
 *     in .env — losing that key bricks the store.
 *
 *  3. Chat reads Vertex credentials from the provider instance (the
 *     SecretStore-backed ProviderStore) through a 30-second cache that
 *     /providers clears on save, so a saved key is used by the next
 *     chat turn.
 *
 * No animations. Pure SVG + CSS. Theme-aware via the shared
 * _diagram-theme module.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.sss .write-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.sss .write-card.profile { stroke: var(--dgm-edge-operator); }
.dgm-root.sss .write-card.providers { stroke: var(--dgm-edge-shared); }
.dgm-root.sss .write-card.firstboot { stroke: var(--dgm-state-info); }
.dgm-root.sss .write-card.connectors { stroke: var(--dgm-edge-compose); }
.dgm-root.sss .write-card.envoverlay { stroke: var(--dgm-edge-iap); stroke-dasharray: 8 6; }

.dgm-root.sss .secret-store-bg {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.6;
}
.dgm-root.sss .secret-store-glow {
  fill: var(--dgm-edge-shared);
  opacity: 0.10;
}
.dgm-root.sss .secret-store-title {
  font-size: 22px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
  letter-spacing: -0.01em;
}
.dgm-root.sss .secret-store-tag {
  fill: var(--dgm-edge-shared);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
.dgm-root.sss .secret-store-detail {
  font-size: 11.5px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sss .secret-store-key {
  font-size: 11.5px;
  fill: var(--dgm-edge-shared);
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}

.dgm-root.sss .write-name {
  font-size: 13px;
  font-weight: 700;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sss .write-detail {
  font-size: 10.5px;
  fill: var(--dgm-text-soft);
}
.dgm-root.sss .write-path {
  font-size: 10px;
  fill: var(--dgm-text-muted);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sss .read-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.4;
}
.dgm-root.sss .read-name {
  font-size: 13px;
  font-weight: 700;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sss .read-detail {
  font-size: 10.5px;
  fill: var(--dgm-text-soft);
}
.dgm-root.sss .converge-edge {
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.3;
  fill: none;
}
.dgm-root.sss .converge-edge.profile { stroke: var(--dgm-edge-operator); }
.dgm-root.sss .converge-edge.providers { stroke: var(--dgm-edge-shared); }
.dgm-root.sss .converge-edge.firstboot { stroke: var(--dgm-state-info); }
.dgm-root.sss .converge-edge.connectors { stroke: var(--dgm-edge-compose); }
.dgm-root.sss .converge-edge.envoverlay {
  stroke: var(--dgm-edge-iap);
  stroke-dasharray: 6 5;
}
.dgm-root.sss .fanout-edge {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.4;
  fill: none;
}
.dgm-root.sss .lock-icon {
  fill: none;
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dgm-root.sss .legend-pip {
  font-size: 11px;
  fill: var(--dgm-text-soft);
}
.dgm-root.sss .legend-pip-strong {
  font-size: 11px;
  fill: var(--dgm-text-main);
  font-weight: 700;
}
.dgm-root.sss .upgrade-band {
  fill: var(--dgm-state-success);
  opacity: 0.10;
}
.dgm-root.sss .upgrade-band-text {
  font-size: 10.5px;
  fill: var(--dgm-state-success);
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
`;

interface WriteSurface {
  id: string;
  variant: "firstboot" | "providers" | "connectors" | "profile" | "envoverlay";
  name: string;
  detail: string;
  path: string;
}

interface ReadSurface {
  id: string;
  variant: "live";
  name: string;
  detail: string;
}

const WRITES: WriteSurface[] = [
  {
    id: "firstboot",
    variant: "firstboot",
    name: "entrypoint · FIRST BOOT",
    detail: "Seeds the admin hash from the installer's .env.",
    path: "PHANTOM_DEFAULT_ADMIN_PASSWORD → /ui/auth/admin/password_hash",
  },
  {
    id: "providers",
    variant: "providers",
    name: "/providers/config",
    detail: "Vertex project, region and key JSON.",
    path: "/api/agent/providers/config → MCP /api/v1/providers",
  },
  {
    id: "connectors",
    variant: "connectors",
    name: "/connectors/[id]",
    detail: "Per-instance edits — caldera, xsiam, xlog credentials.",
    path: "/api/agent/instances → MCP /api/v1/instances",
  },
  {
    id: "profile",
    variant: "profile",
    name: "/profile",
    detail: "UI password change. PBKDF2 hash, not plaintext.",
    path: "/api/auth/change-password → MCP ui_auth.set_password",
  },
  {
    id: "envoverlay",
    variant: "envoverlay",
    name: "EnvSecretStore overlay",
    detail: "Read-time shadow — env values mask stored secrets without rewriting them.",
    path: "process.env → secret_store.read() returns env value if matching path",
  },
];

const READS: ReadSurface[] = [
  {
    id: "mcp-tools",
    variant: "live",
    name: "MCP tool calls",
    detail: "caldera.*, xsiam.*, xlog.*",
  },
  {
    id: "ui-auth",
    variant: "live",
    name: "UI login verify",
    detail: "PBKDF2 verify on /api/auth/login",
  },
  {
    id: "chat-vertex",
    variant: "live",
    name: "Chat → Vertex",
    detail: "Provider instance, 30 s cache, cleared on save",
  },
];

const VIEW_W = 1200;
const VIEW_H = 760;

const HERO_W = 540;
const HERO_H = 220;
const HERO_X = (VIEW_W - HERO_W) / 2;
const HERO_Y = (VIEW_H - HERO_H) / 2 - 20;

const WRITE_TOP = 60;
const WRITE_H = 110;
const WRITE_W = 220;
const WRITE_GAP = 18;
const WRITES_TOTAL_W = WRITES.length * WRITE_W + (WRITES.length - 1) * WRITE_GAP;
const WRITES_START_X = (VIEW_W - WRITES_TOTAL_W) / 2;

const READ_TOP = HERO_Y + HERO_H + 80;
const READ_W = 250;
const READ_H = 90;
const READ_GAP = 30;
const READS_TOTAL_W = READS.length * READ_W + (READS.length - 1) * READ_GAP;
const READS_START_X = (VIEW_W - READS_TOTAL_W) / 2;

function writeX(idx: number): number {
  return WRITES_START_X + idx * (WRITE_W + WRITE_GAP);
}

function readX(idx: number): number {
  return READS_START_X + idx * (READ_W + READ_GAP);
}

export function SecretStoreFlow() {
  return (
    <div className="dgm-root sss">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="sss-title sss-desc"
      >
        <title id="sss-title">SecretStore Flow</title>
        <desc id="sss-desc">
          Five operator-credential write surfaces converge on the SecretStore
          (encrypted with AES-256-GCM, persisted under /app/data/secrets/ on
          the phantom_mcp_data volume). The store fans out to MCP tool calls, UI auth, and
          chat, which reads Vertex credentials from the provider instance.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="sss-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        {/* Background */}
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#sss-dot-grid)" />

        {/* Title + subtitle */}
        <text x="60" y="40" className="title" fontSize="22">
          SecretStore Flow
        </text>
        <text x="60" y="62" className="detail" fontSize="13">
          Five write surfaces converge → encrypted-at-rest store → live consumers fan out.
        </text>

        {/* WRITES (top) */}
        {WRITES.map((w, i) => {
          const x = writeX(i);
          return (
            <g key={w.id}>
              <rect
                className={`write-card ${w.variant}`}
                x={x}
                y={WRITE_TOP + 30}
                width={WRITE_W}
                height={WRITE_H}
                rx="10"
              />
              <text className="write-name" x={x + 14} y={WRITE_TOP + 56}>
                {w.name}
              </text>
              <text className="write-detail" x={x + 14} y={WRITE_TOP + 76}>
                {wrap(w.detail, 30)[0]}
              </text>
              {wrap(w.detail, 30)[1] && (
                <text className="write-detail" x={x + 14} y={WRITE_TOP + 90}>
                  {wrap(w.detail, 30)[1]}
                </text>
              )}
              <text className="write-path" x={x + 14} y={WRITE_TOP + 113}>
                {wrap(w.path, 33)[0]}
              </text>
              {wrap(w.path, 33)[1] && (
                <text className="write-path" x={x + 14} y={WRITE_TOP + 127}>
                  {wrap(w.path, 33)[1]}
                </text>
              )}
            </g>
          );
        })}

        {/* Converge edges (writes → store top) */}
        {WRITES.map((w, i) => {
          const x = writeX(i) + WRITE_W / 2;
          const y0 = WRITE_TOP + 30 + WRITE_H;
          const yMid = HERO_Y - 8;
          const xTarget = HERO_X + 60 + i * ((HERO_W - 120) / (WRITES.length - 1));
          return (
            <path
              key={`edge-${w.id}`}
              className={`converge-edge ${w.variant}`}
              d={`M ${x} ${y0} C ${x} ${y0 + 24}, ${xTarget} ${yMid - 24}, ${xTarget} ${yMid}`}
            />
          );
        })}

        {/* HERO — SecretStore */}
        <rect
          className="secret-store-glow"
          x={HERO_X - 22}
          y={HERO_Y - 22}
          width={HERO_W + 44}
          height={HERO_H + 44}
          rx="32"
        />
        <rect
          className="secret-store-bg"
          x={HERO_X}
          y={HERO_Y}
          width={HERO_W}
          height={HERO_H}
          rx="20"
        />
        {/* Lock icon */}
        <g transform={`translate(${HERO_X + 32} ${HERO_Y + 36})`}>
          <rect
            className="lock-icon"
            x="0"
            y="14"
            width="28"
            height="20"
            rx="3"
            fill="none"
          />
          <path
            className="lock-icon"
            d="M 6 14 V 8 a 8 8 0 0 1 16 0 V 14"
            fill="none"
          />
          <circle className="lock-icon" cx="14" cy="24" r="2" fill="none" />
        </g>

        <text
          className="secret-store-tag"
          x={HERO_X + 80}
          y={HERO_Y + 30}
        >
          ENCRYPTED · NAMED VOLUME
        </text>
        <text
          className="secret-store-title"
          x={HERO_X + 80}
          y={HERO_Y + 60}
        >
          SecretStore
        </text>
        <text
          className="secret-store-detail"
          x={HERO_X + 80}
          y={HERO_Y + 86}
        >
          /app/data/secrets/&lt;path&gt;
        </text>
        <text
          className="secret-store-detail"
          x={HERO_X + 80}
          y={HERO_Y + 106}
        >
          AES-256-GCM, 96-bit nonce per secret
        </text>
        <text
          className="secret-store-detail"
          x={HERO_X + 80}
          y={HERO_Y + 126}
        >
          Key is PHANTOM_SECRET_KEK (env-pinned)
        </text>
        {/* Path-prefix exemplars */}
        <text
          className="secret-store-key"
          x={HERO_X + 80}
          y={HERO_Y + 152}
        >
          /providers/&lt;id&gt;/&lt;instance&gt;/&lt;slot&gt;
        </text>
        <text
          className="secret-store-key"
          x={HERO_X + 80}
          y={HERO_Y + 170}
        >
          /connectors/&lt;id&gt;/&lt;instance&gt;/&lt;slot&gt;
        </text>
        <text
          className="secret-store-key"
          x={HERO_X + 80}
          y={HERO_Y + 188}
        >
          /ui/auth/&lt;user&gt;/password_hash
        </text>

        {/* Upgrade-survival band callout (right side of hero) */}
        <g transform={`translate(${HERO_X + HERO_W - 200} ${HERO_Y + 18})`}>
          <rect
            className="upgrade-band"
            x="0"
            y="0"
            width="180"
            height="28"
            rx="6"
          />
          <text
            className="upgrade-band-text"
            x="14"
            y="19"
          >
            SURVIVES UPGRADE
          </text>
        </g>

        {/* Fan-out edges (store bottom → reads) */}
        {READS.map((r, i) => {
          const xTarget = readX(i) + READ_W / 2;
          const yTarget = READ_TOP;
          const x0 = HERO_X + 60 + i * ((HERO_W - 120) / (READS.length - 1));
          const y0 = HERO_Y + HERO_H;
          return (
            <path
              key={`fanout-${r.id}`}
              className="fanout-edge"
              d={`M ${x0} ${y0} C ${x0} ${y0 + 30}, ${xTarget} ${yTarget - 30}, ${xTarget} ${yTarget}`}
            />
          );
        })}

        {/* READS (bottom) */}
        {READS.map((r, i) => {
          const x = readX(i);
          return (
            <g key={r.id}>
              <rect
                className="read-card"
                x={x}
                y={READ_TOP}
                width={READ_W}
                height={READ_H}
                rx="10"
              />
              <text className="read-name" x={x + 14} y={READ_TOP + 28}>
                {r.name}
              </text>
              <text className="read-detail" x={x + 14} y={READ_TOP + 50}>
                {wrap(r.detail, 33)[0]}
              </text>
              {wrap(r.detail, 33)[1] && (
                <text className="read-detail" x={x + 14} y={READ_TOP + 64}>
                  {wrap(r.detail, 33)[1]}
                </text>
              )}
            </g>
          );
        })}

        {/* Legend (bottom-left) */}
        <g transform={`translate(60 ${VIEW_H - 60})`}>
          <text className="legend-title">Edge classes</text>
          <line
            className="legend-line"
            x1="0"
            y1="14"
            x2="36"
            y2="14"
            stroke="var(--dgm-edge-operator)"
          />
          <text className="legend-text" x="44" y="18">
            live read/write
          </text>
          <line
            className="legend-line dashed"
            x1="160"
            y1="14"
            x2="196"
            y2="14"
            stroke="var(--dgm-edge-iap)"
          />
          <text className="legend-text" x="204" y="18">
            env overlay (read-time only)
          </text>
        </g>
      </svg>
    </div>
  );
}

/**
 * Minimal word-wrap so card text fits within the card width without
 * needing a full SVG-foreignObject layout. Returns the first two
 * lines of the input, breaking on word boundaries when the running
 * length exceeds `maxChars`. Anything beyond two lines is truncated
 * with an ellipsis on line 2.
 */
function wrap(text: string, maxChars: number): [string, string | null] {
  if (text.length <= maxChars) return [text, null];
  const words = text.split(/\s+/);
  const lines: string[] = ["", ""];
  let lineIdx = 0;
  for (const w of words) {
    const candidate = lines[lineIdx] ? `${lines[lineIdx]} ${w}` : w;
    if (candidate.length <= maxChars) {
      lines[lineIdx] = candidate;
    } else if (lineIdx === 0) {
      lineIdx = 1;
      lines[lineIdx] = w;
    } else {
      // would overflow line 2 — truncate
      lines[1] = lines[1] + " …";
      break;
    }
  }
  return [lines[0], lines[1] || null];
}
