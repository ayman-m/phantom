"use client";

/**
 * Phantom Substrate Composition.
 *
 * Foundation substrates (bottom row) are reused by composite features
 * (top row) rather than duplicated. The visual argument: features are
 * mostly glue, not new infrastructure. Edges show which substrate each
 * composite feature reuses, with reuse-counts.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.sub .substrate {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-stroke-strong);
  stroke-width: 2;
}
.dgm-root.sub .substrate-tag {
  fill: var(--dgm-text-soft);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.2em;
}
.dgm-root.sub .substrate-name {
  fill: var(--dgm-text-main);
  font-size: 16px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .substrate-detail {
  fill: var(--dgm-text-soft);
  font-size: 11.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .composite {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.2;
}
.dgm-root.sub .composite-name {
  fill: var(--dgm-edge-shared);
  font-size: 16px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .composite-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .reuse-edge {
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.5;
  fill: none;
  opacity: 0.6;
}
.dgm-root.sub .reuse-label {
  fill: var(--dgm-edge-shared);
  font-size: 10px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .stat-card {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-stroke-muted);
}
.dgm-root.sub .stat-num {
  fill: var(--dgm-edge-shared);
  font-size: 28px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.sub .stat-label {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-weight: 600;
}
`;

interface Substrate {
  id: string;
  name: string;
  detail: string;
}

interface Composite {
  id: string;
  name: string;
  detail: string;
  /** substrate ids this feature reuses */
  reuses: string[];
}

const SUBSTRATES: Substrate[] = [
  { id: "audit", name: "audit_log", detail: "append-only · universal queryable surface" },
  { id: "tasks", name: "tasks.db", detail: "row-per-entity state machine" },
  { id: "hooks", name: "hooks.db", detail: "policy fabric · 6 fire-sites" },
  { id: "tool_meta", name: "tool_metadata", detail: "denormalised flags on tool_call" },
  { id: "plugins", name: "plugin loader", detail: "manifest-driven contributions" },
];

const COMPOSITES: Composite[] = [
  {
    id: "plan",
    name: "plan_mode",
    detail: "model proposes plan · operator gates",
    reuses: ["audit", "hooks"],
  },
  {
    id: "subagents",
    name: "subagents",
    detail: "scoped child sessions · sidechain transcript",
    reuses: ["audit", "tasks", "hooks", "plugins"],
  },
  {
    id: "cost",
    name: "cost rollup",
    detail: "per-turn cost row + window aggregation",
    reuses: ["audit", "tool_meta"],
  },
  {
    id: "approval",
    name: "approval queue",
    detail: "tier-2/3 gate · operator decision",
    reuses: ["audit", "tool_meta"],
  },
  {
    id: "vendor_plug",
    name: "vendor plugins",
    detail: "skills + scenarios + agents from a manifest",
    reuses: ["plugins", "audit"],
  },
];

const VIEW_W = 1520;
const VIEW_H = 920;
const SUBSTRATE_W = 240;
const SUBSTRATE_H = 96;
const SUBSTRATE_GAP = 32;
const SUBSTRATE_Y = 580;

const COMPOSITE_W = 230;
const COMPOSITE_H = 96;
const COMPOSITE_GAP = 28;
const COMPOSITE_Y = 200;

export function SubstrateComposition() {
  const subTotalW = SUBSTRATES.length * SUBSTRATE_W + (SUBSTRATES.length - 1) * SUBSTRATE_GAP;
  const subStartX = (VIEW_W - subTotalW) / 2;
  const subX = (i: number) => subStartX + i * (SUBSTRATE_W + SUBSTRATE_GAP);

  const compTotalW = COMPOSITES.length * COMPOSITE_W + (COMPOSITES.length - 1) * COMPOSITE_GAP;
  const compStartX = (VIEW_W - compTotalW) / 2;
  const compX = (i: number) => compStartX + i * (COMPOSITE_W + COMPOSITE_GAP);

  // Map substrate id → index
  const subIdx = Object.fromEntries(SUBSTRATES.map((s, i) => [s.id, i]));
  const compIdx = Object.fromEntries(COMPOSITES.map((c, i) => [c.id, i]));

  // Reuse counts per substrate
  const reuseCount: Record<string, number> = {};
  for (const c of COMPOSITES) {
    for (const r of c.reuses) {
      reuseCount[r] = (reuseCount[r] || 0) + 1;
    }
  }

  return (
    <div className="dgm-root sub">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="sub-title sub-desc"
      >
        <title id="sub-title">Substrate Composition</title>
        <desc id="sub-desc">
          Foundation substrates at the bottom are reused by composite features
          at the top.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="sub-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#sub-dot-grid)" />

        <text x="60" y="44" className="title" fontSize="22">
          Substrate Composition
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Composite features (top) reuse foundation substrates (bottom). New
          features are mostly glue — adding one rarely needs new infrastructure.
        </text>

        {/* Section labels */}
        <text x="60" y={COMPOSITE_Y - 24} className="lane-label" fontSize="11">
          COMPOSITE FEATURES
        </text>
        <text x="60" y={SUBSTRATE_Y - 24} className="lane-label" fontSize="11">
          FOUNDATION SUBSTRATES
        </text>

        {/* Reuse edges (drawn first) */}
        {COMPOSITES.flatMap((c, ci) =>
          c.reuses.map((rid, ri) => {
            const fromX = compX(ci) + COMPOSITE_W / 2;
            const fromY = COMPOSITE_Y + COMPOSITE_H;
            const toIdx = subIdx[rid];
            const toX = subX(toIdx) + SUBSTRATE_W / 2;
            const toY = SUBSTRATE_Y;
            // Add a small horizontal offset so multiple edges to same
            // substrate from different composites land at different x
            const offset = (ri - (c.reuses.length - 1) / 2) * 18;
            return (
              <path
                key={`${c.id}-${rid}`}
                className="reuse-edge"
                d={`M ${fromX + offset} ${fromY} C ${fromX + offset} ${(fromY + toY) / 2}, ${toX + offset} ${(fromY + toY) / 2}, ${toX + offset} ${toY}`}
              />
            );
          })
        )}

        {/* Composites */}
        {COMPOSITES.map((c, ci) => {
          const x = compX(ci);
          return (
            <g key={c.id}>
              <rect
                className="composite"
                x={x}
                y={COMPOSITE_Y}
                width={COMPOSITE_W}
                height={COMPOSITE_H}
                rx="14"
              />
              <text
                className="substrate-tag"
                x={x + 18}
                y={COMPOSITE_Y + 22}
                fill="var(--dgm-edge-shared)"
              >
                COMPOSITE
              </text>
              <text className="composite-name" x={x + 18} y={COMPOSITE_Y + 48}>
                {c.name}
              </text>
              <text className="composite-detail" x={x + 18} y={COMPOSITE_Y + 70}>
                {c.detail}
              </text>
              <text
                className="composite-detail"
                x={x + 18}
                y={COMPOSITE_Y + 88}
                fontSize="10"
                fill="var(--dgm-text-muted)"
              >
                reuses: {c.reuses.length} substrate{c.reuses.length === 1 ? "" : "s"}
              </text>
            </g>
          );
        })}

        {/* Substrates */}
        {SUBSTRATES.map((s, si) => {
          const x = subX(si);
          const count = reuseCount[s.id] || 0;
          return (
            <g key={s.id}>
              <rect
                className="substrate"
                x={x}
                y={SUBSTRATE_Y}
                width={SUBSTRATE_W}
                height={SUBSTRATE_H}
                rx="14"
              />
              <text
                className="substrate-tag"
                x={x + 18}
                y={SUBSTRATE_Y + 22}
              >
                FOUNDATION
              </text>
              <text className="substrate-name" x={x + 18} y={SUBSTRATE_Y + 48}>
                {s.name}
              </text>
              <text className="substrate-detail" x={x + 18} y={SUBSTRATE_Y + 70}>
                {s.detail}
              </text>
              {/* Reuse count chip */}
              {count > 0 && (
                <g transform={`translate(${x + SUBSTRATE_W - 50} ${SUBSTRATE_Y + 22})`}>
                  <rect
                    width="38"
                    height="22"
                    rx="6"
                    fill="rgba(247,183,49,0.15)"
                    stroke="var(--dgm-edge-shared)"
                  />
                  <text
                    x="19"
                    y="15"
                    textAnchor="middle"
                    className="reuse-label"
                  >
                    {`×${count}`}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* Stats panel */}
        <g transform={`translate(${VIEW_W - 460} 80)`}>
          <rect
            x="0"
            y="0"
            width="400"
            height="100"
            rx="14"
            className="stat-card"
          />
          <g transform="translate(28 0)">
            <text className="stat-num" x="0" y="46">
              5
            </text>
            <text className="stat-label" x="0" y="68">
              substrates
            </text>
          </g>
          <g transform="translate(160 0)">
            <text className="stat-num" x="0" y="46">
              5
            </text>
            <text className="stat-label" x="0" y="68">
              composites
            </text>
          </g>
          <g transform="translate(290 0)">
            <text className="stat-num" x="0" y="46">
              13
            </text>
            <text className="stat-label" x="0" y="68">
              reuse edges
            </text>
          </g>
        </g>

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
            Why this matters
          </text>
          <text className="legend-text" x="180" y="4">
            Subagents shipped in ~3,200 LOC by reusing 4 substrates. New
            features are feature decisions, not architectural ones — the cost
            of an idea is mostly its glue, not its plumbing.
          </text>
        </g>
      </svg>
    </div>
  );
}
