"use client";

/**
 * Phantom Context & Memory Pipeline.
 *
 * What happens to chat history before every turn: load → token-budget
 * walk → maybe-compact → maybe-cache-hit → memory-augment. Two
 * decision points fork the flow (compaction edge, Vertex cache hit).
 * The memory ranking pipeline (vec → MMR → decay → FTS5) attaches as
 * a parallel side-branch feeding into "memory-augment".
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.cmp .stage-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.cmp .stage-card.hero {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.8;
}
.dgm-root.cmp .decision {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.8;
}
.dgm-root.cmp .branch-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.4;
  stroke-dasharray: 0;
}
.dgm-root.cmp .memory-stack {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-edge-compose);
  stroke-width: 1.4;
}
.dgm-root.cmp .stage-num {
  fill: var(--dgm-edge-operator);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.18em;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.cmp .stage-title {
  fill: var(--dgm-text-main);
  font-size: 14px;
  font-weight: 700;
}
.dgm-root.cmp .stage-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.cmp .branch-title {
  fill: var(--dgm-edge-shared);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.dgm-root.cmp .mem-rank-step {
  fill: var(--dgm-text-main);
  font-size: 12px;
  font-weight: 700;
}
.dgm-root.cmp .mem-rank-detail {
  fill: var(--dgm-text-soft);
  font-size: 10.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.cmp .branch-no {
  fill: var(--dgm-text-muted);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.dgm-root.cmp .branch-yes {
  fill: var(--dgm-edge-shared);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.dgm-root.cmp .step-edge {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.8;
  fill: none;
}
.dgm-root.cmp .branch-edge-yes {
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.6;
  fill: none;
  stroke-dasharray: 4 5;
}
.dgm-root.cmp .branch-edge-no {
  stroke: var(--dgm-text-muted);
  stroke-width: 1.4;
  fill: none;
}
.dgm-root.cmp .mem-edge {
  stroke: var(--dgm-edge-compose);
  stroke-width: 1.4;
  fill: none;
}
`;

const VIEW_W = 1520;
const VIEW_H = 940;

// Main pipeline stages (5 in a horizontal row)
const PIPELINE_TOP = 240;
const STAGE_W = 220;
const STAGE_H = 96;
const STAGE_GAP = 50;
const STAGES = [
  {
    n: 1,
    title: "Load history",
    detail: "loadSessionHistory(sid)",
    icon: (
      <g>
        <line x1="-7" y1="-6" x2="7" y2="-6" />
        <line x1="-7" y1="-2" x2="5" y2="-2" />
        <line x1="-7" y1="2" x2="6" y2="2" />
        <line x1="-7" y1="6" x2="4" y2="6" />
      </g>
    ),
  },
  {
    n: 2,
    title: "Token-budget walk",
    detail: "newest → oldest · 30% margin",
    icon: (
      <g>
        <rect x="-8" y="-6" width="16" height="12" rx="2" fill="none" />
        <line x1="-4" y1="-6" x2="-4" y2="6" />
        <line x1="0" y1="-6" x2="0" y2="6" />
        <line x1="4" y1="-6" x2="4" y2="6" />
      </g>
    ),
  },
  {
    n: 3,
    title: "Compaction (auto)",
    detail: "drop > N? → summarise older",
    icon: (
      <g>
        <path d="M -7 -5 L 7 -5 L 0 5 Z" fill="none" />
        <line x1="-3" y1="-2" x2="3" y2="-2" />
      </g>
    ),
  },
  {
    n: 4,
    title: "Vertex cache lookup",
    detail: "cachedContents API",
    icon: (
      <g>
        <polyline points="3,-8 -3,1 1,1 -2,8 4,-1 0,-1 3,-8" fill="none" />
      </g>
    ),
  },
  {
    n: 5,
    title: "Memory augment",
    detail: "inject relevant entries",
    icon: (
      <g>
        <ellipse cx="0" cy="-5" rx="7" ry="2.5" fill="none" />
        <path d="M -7 -5 V 5 a 7 2.5 0 0 0 14 0 V -5" fill="none" />
      </g>
    ),
  },
];

// Branch boxes shown above/below the main pipeline
const BRANCHES = [
  {
    id: "compact-yes",
    parentN: 3,
    side: "below",
    title: "compact",
    detail: "summarise dropped messages → checkpoint",
    label: "yes",
  },
  {
    id: "cache-yes",
    parentN: 4,
    side: "below",
    title: "cache hit",
    detail: "75% cheaper input tokens",
    label: "yes",
  },
];

// Memory ranking pipeline stack (parallel side-branch feeding stage 5)
const MEM_STACK = [
  { name: "vector retrieval", detail: "top-K cosine via sqlite-vec" },
  { name: "MMR rerank", detail: "λ × sim − (1−λ) × max_pair" },
  { name: "temporal decay", detail: "exp(−age × λ)" },
  { name: "FTS5 promotion", detail: "literal hits → top of result" },
];

const MEM_TOP = 530;
const MEM_W = 240;
const MEM_H = 64;
const MEM_GAP = 16;
const MEM_LEFT = 100; // far left of the row

export function ContextMemoryPipeline() {
  const totalGridW = STAGES.length * STAGE_W + (STAGES.length - 1) * STAGE_GAP;
  const startX = (VIEW_W - totalGridW) / 2;
  const stageX = (i: number) => startX + i * (STAGE_W + STAGE_GAP);
  const stageCenterY = PIPELINE_TOP + STAGE_H / 2;

  return (
    <div className="dgm-root cmp">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="cmp-title cmp-desc"
      >
        <title id="cmp-title">Context & Memory Pipeline</title>
        <desc id="cmp-desc">
          Five-stage pipeline showing how chat history is loaded, budgeted,
          compacted, cached, and augmented with memory before each turn.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="cmp-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#cmp-dot-grid)" />

        {/* Header */}
        <text x="60" y="44" className="title" fontSize="22">
          Context &amp; Memory Pipeline
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Five sequential stages run before every chat turn. Two stages have
          decision branches; memory augmentation pulls from a parallel
          ranking pipeline.
        </text>

        {/* Pipeline edges (drawn first so cards stack on top) */}
        {STAGES.slice(0, -1).map((_, i) => {
          const fromX = stageX(i) + STAGE_W;
          const toX = stageX(i + 1);
          return (
            <line
              key={`pe-${i}`}
              className="step-edge"
              x1={fromX}
              y1={stageCenterY}
              x2={toX}
              y2={stageCenterY}
              markerEnd="url(#dgm-arrow-operator)"
            />
          );
        })}

        {/* Stage cards */}
        {STAGES.map((s, i) => {
          const x = stageX(i);
          return (
            <g key={s.n}>
              <rect
                className={`stage-card ${i === 1 || i === 4 ? "hero" : ""}`}
                x={x}
                y={PIPELINE_TOP}
                width={STAGE_W}
                height={STAGE_H}
                rx="14"
              />
              <text className="stage-num" x={x + 18} y={PIPELINE_TOP + 26}>
                {`STAGE ${s.n}`}
              </text>
              <circle
                cx={x + STAGE_W - 32}
                cy={PIPELINE_TOP + 28}
                r="14"
                fill="var(--dgm-badge-bg)"
                stroke="var(--dgm-badge-stroke)"
                strokeWidth="1"
              />
              <g
                transform={`translate(${x + STAGE_W - 32} ${PIPELINE_TOP + 28})`}
                stroke="var(--dgm-text-main)"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              >
                {s.icon}
              </g>
              <text
                className="stage-title"
                x={x + 18}
                y={PIPELINE_TOP + 56}
              >
                {s.title}
              </text>
              <text
                className="stage-detail"
                x={x + 18}
                y={PIPELINE_TOP + 78}
              >
                {s.detail}
              </text>
            </g>
          );
        })}

        {/* Branch: compaction (under stage 3) */}
        {(() => {
          const stageIdx = 2;
          const cx = stageX(stageIdx) + STAGE_W / 2;
          const branchTop = PIPELINE_TOP + STAGE_H + 60;
          const branchW = 280;
          const branchH = 70;
          const branchX = cx - branchW / 2;
          return (
            <g>
              {/* yes-branch label */}
              <text
                className="branch-yes"
                x={cx + 8}
                y={PIPELINE_TOP + STAGE_H + 24}
              >
                YES
              </text>
              {/* dashed branch edge */}
              <path
                className="branch-edge-yes"
                d={`M ${cx} ${PIPELINE_TOP + STAGE_H} V ${branchTop}`}
              />
              {/* return-arrow back into pipeline (just to next stage) */}
              <path
                className="branch-edge-yes"
                d={`M ${branchX + branchW} ${branchTop + branchH / 2} H ${stageX(stageIdx + 1) - 10} V ${stageCenterY + 1}`}
              />
              <rect
                className="branch-card"
                x={branchX}
                y={branchTop}
                width={branchW}
                height={branchH}
                rx="12"
              />
              <text
                className="branch-title"
                x={branchX + 18}
                y={branchTop + 26}
              >
                COMPACT &amp; CHECKPOINT
              </text>
              <text
                className="stage-detail"
                x={branchX + 18}
                y={branchTop + 50}
              >
                summariser → system msg kind:checkpoint
              </text>
            </g>
          );
        })()}

        {/* Branch: cache-hit (under stage 4) */}
        {(() => {
          const stageIdx = 3;
          const cx = stageX(stageIdx) + STAGE_W / 2;
          const branchTop = PIPELINE_TOP + STAGE_H + 60;
          const branchW = 240;
          const branchH = 70;
          const branchX = cx - branchW / 2;
          return (
            <g>
              <text
                className="branch-yes"
                x={cx + 8}
                y={PIPELINE_TOP + STAGE_H + 24}
              >
                HIT
              </text>
              <path
                className="branch-edge-yes"
                d={`M ${cx} ${PIPELINE_TOP + STAGE_H} V ${branchTop}`}
              />
              <path
                className="branch-edge-yes"
                d={`M ${branchX + branchW} ${branchTop + branchH / 2} H ${stageX(stageIdx + 1) - 10} V ${stageCenterY + 1}`}
              />
              <rect
                className="branch-card"
                x={branchX}
                y={branchTop}
                width={branchW}
                height={branchH}
                rx="12"
              />
              <text
                className="branch-title"
                x={branchX + 18}
                y={branchTop + 26}
              >
                CACHED INPUT
              </text>
              <text
                className="stage-detail"
                x={branchX + 18}
                y={branchTop + 50}
              >
                ~25% of full token rate
              </text>
            </g>
          );
        })()}

        {/* Memory ranking sub-pipeline (left side, feeding stage 5) */}
        <text
          x={MEM_LEFT}
          y={MEM_TOP - 12}
          className="lane-label"
          fontSize="11"
        >
          MEMORY RANKING PIPELINE
        </text>
        {MEM_STACK.map((m, i) => {
          const x = MEM_LEFT + i * (MEM_W + MEM_GAP);
          return (
            <g key={m.name}>
              <rect
                className="memory-stack"
                x={x}
                y={MEM_TOP}
                width={MEM_W}
                height={MEM_H}
                rx="12"
              />
              <text className="mem-rank-step" x={x + 16} y={MEM_TOP + 24}>
                {`${i + 1}. ${m.name}`}
              </text>
              <text
                className="mem-rank-detail"
                x={x + 16}
                y={MEM_TOP + 46}
              >
                {m.detail}
              </text>
              {i < MEM_STACK.length - 1 && (
                <line
                  className="mem-edge"
                  x1={x + MEM_W}
                  y1={MEM_TOP + MEM_H / 2}
                  x2={x + MEM_W + MEM_GAP}
                  y2={MEM_TOP + MEM_H / 2}
                  markerEnd="url(#dgm-arrow-compose)"
                />
              )}
            </g>
          );
        })}
        {/* Mem pipeline → stage 5 connector */}
        {(() => {
          const lastMemX =
            MEM_LEFT + (MEM_STACK.length - 1) * (MEM_W + MEM_GAP) + MEM_W;
          const lastMemY = MEM_TOP + MEM_H / 2;
          const stage5X = stageX(4) + STAGE_W / 2;
          const stage5Bottom = PIPELINE_TOP + STAGE_H;
          // L-shaped edge from end-of-memory-pipeline up + right to bottom of stage 5
          return (
            <path
              className="mem-edge"
              d={`M ${lastMemX} ${lastMemY} H ${stage5X - 30} Q ${stage5X - 30} ${lastMemY - 14} ${stage5X - 30 + 14} ${lastMemY - 14} L ${stage5X} ${lastMemY - 14} V ${stage5Bottom + 4}`}
              markerEnd="url(#dgm-arrow-compose)"
            />
          );
        })()}

        {/* Footer legend */}
        <g transform={`translate(60 ${VIEW_H - 70})`}>
          <rect
            x="0"
            y="-18"
            width={VIEW_W - 120}
            height="58"
            rx="14"
            fill="var(--dgm-panel)"
            stroke="var(--dgm-stroke-muted)"
          />
          <text className="legend-title" x="20" y="4">
            Reading the diagram
          </text>
          <line
            className="legend-line"
            x1="220"
            y1="0"
            x2="256"
            y2="0"
            stroke="var(--dgm-edge-operator)"
          />
          <text className="legend-text" x="266" y="4">
            main pipeline
          </text>
          <line
            className="legend-line"
            x1="380"
            y1="0"
            x2="416"
            y2="0"
            stroke="var(--dgm-edge-shared)"
            strokeDasharray="4 5"
          />
          <text className="legend-text" x="426" y="4">
            decision branch
          </text>
          <line
            className="legend-line"
            x1="552"
            y1="0"
            x2="588"
            y2="0"
            stroke="var(--dgm-edge-compose)"
          />
          <text className="legend-text" x="598" y="4">
            memory ranking
          </text>
          <text className="legend-text" x="20" y="28" fontSize="11">
            Stages 3 and 4 take a side-path on YES/HIT and rejoin the main
            flow. Stage 5 attaches the memory-ranking sub-pipeline so retrieved
            entries land in the prompt before the model call.
          </text>
        </g>
      </svg>
    </div>
  );
}
