"use client";

/**
 * Phantom Agent Knowledge Surfaces.
 *
 * Three knowledge surfaces the agent draws on at runtime: Tools (MCP
 * tools registered from connector code), Skills (markdown procedural
 * recipes that bias tool selection), and Knowledge Bases (vector-
 * indexed reference content). Each column traces the path from
 * bundle source → loader → runtime catalog → chat-route consumer.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.aks .col-bg {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-stroke-muted);
}
.dgm-root.aks .col-title {
  fill: var(--dgm-text-main);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.01em;
}
.dgm-root.aks .col-sub {
  fill: var(--dgm-text-soft);
  font-size: 11.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.aks .step-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.aks .step-card.tools { stroke: var(--dgm-edge-compose); }
.dgm-root.aks .step-card.skills { stroke: var(--dgm-edge-shared); }
.dgm-root.aks .step-card.kb { stroke: var(--dgm-edge-external); }
.dgm-root.aks .step-tag {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}
.dgm-root.aks .step-tag.tools { fill: var(--dgm-edge-compose); }
.dgm-root.aks .step-tag.skills { fill: var(--dgm-edge-shared); }
.dgm-root.aks .step-tag.kb { fill: var(--dgm-edge-external); }
.dgm-root.aks .step-name {
  fill: var(--dgm-text-main);
  font-size: 14px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.aks .step-detail {
  fill: var(--dgm-text-soft);
  font-size: 11px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.aks .col-edge {
  stroke-width: 2;
  fill: none;
}
.dgm-root.aks .col-edge.tools { stroke: var(--dgm-edge-compose); }
.dgm-root.aks .col-edge.skills { stroke: var(--dgm-edge-shared); }
.dgm-root.aks .col-edge.kb { stroke: var(--dgm-edge-external); }
.dgm-root.aks .consumer-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.8;
}
.dgm-root.aks .consumer-title {
  fill: var(--dgm-edge-operator);
  font-size: 16px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.aks .consumer-detail {
  fill: var(--dgm-text-soft);
  font-size: 12px;
}
.dgm-root.aks .feed-edge {
  stroke: var(--dgm-edge-operator);
  stroke-width: 1.8;
  fill: none;
}
`;

interface FlowStep {
  tag: string;
  name: string;
  detail: string;
}

interface KnowledgeColumn {
  id: "tools" | "skills" | "kb";
  title: string;
  sub: string;
  steps: FlowStep[];
}

const COLUMNS: KnowledgeColumn[] = [
  {
    id: "tools",
    title: "Tools (MCP)",
    sub: "~80 tools across 3 connectors",
    steps: [
      {
        tag: "BUNDLE",
        name: "connectors/*.py",
        detail: "Python tool implementations",
      },
      {
        tag: "LOADER",
        name: "connector_loader",
        detail: "register_all_tools() at MCP boot",
      },
      {
        tag: "CATALOG",
        name: "FastMCP registry",
        detail: "tool_metadata.db · tier · concurrencySafe",
      },
      {
        tag: "CONSUMED VIA",
        name: "function_call",
        detail: "model returns name + args → dispatch",
      },
    ],
  },
  {
    id: "skills",
    title: "Skills",
    sub: "markdown · activated by keyword",
    steps: [
      {
        tag: "BUNDLE",
        name: "mcp/skills/**/*.md",
        detail: "foundation · scenarios · validation · workflows",
      },
      {
        tag: "LOADER",
        name: "entrypoint.sh seed",
        detail: "skills-default → /app/skills volume",
      },
      {
        tag: "CATALOG",
        name: "/skills page + DB",
        detail: "lock state + per-workspace overrides",
      },
      {
        tag: "CONSUMED VIA",
        name: "system-prompt inject",
        detail: "load_simulation_skills(keywords=…)",
      },
    ],
  },
  {
    id: "kb",
    title: "Knowledge Bases",
    sub: "vector + FTS5 hybrid retrieval",
    steps: [
      {
        tag: "BUNDLE",
        name: "kbs/*/entries/*.md",
        detail: "phantom-soc · xql-examples",
      },
      {
        tag: "LOADER",
        name: "SqliteKnowledgeBase",
        detail: "boot reconcile · source-hash dedupe",
      },
      {
        tag: "CATALOG",
        name: "per-KB sqlite + vec",
        detail: "embedding cached at write-time",
      },
      {
        tag: "CONSUMED VIA",
        name: "knowledge_search()",
        detail: "find_xql_examples_rag(query, top_k)",
      },
    ],
  },
];

const VIEW_W = 1520;
const VIEW_H = 920;
const COL_W = 420;
const COL_GAP = 30;
const COL_TOP = 130;
const COL_H = 580;
const STEP_W = 360;
const STEP_H = 76;
const STEP_GAP = 24;
const STEPS_TOP_OFFSET = 70; // distance from col top to first step

const consumerTop = COL_TOP + COL_H + 30;
const consumerH = 110;

export function AgentKnowledgeSurfaces() {
  const totalCols = COLUMNS.length;
  const gridW = totalCols * COL_W + (totalCols - 1) * COL_GAP;
  const startX = (VIEW_W - gridW) / 2;
  const colX = (i: number) => startX + i * (COL_W + COL_GAP);

  return (
    <div className="dgm-root aks">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="aks-title aks-desc"
      >
        <title id="aks-title">Agent Knowledge Surfaces</title>
        <desc id="aks-desc">
          Three columns showing how tools, skills, and knowledge bases flow
          from bundle to chat-route runtime.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="aks-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#aks-dot-grid)" />

        <text x="60" y="44" className="title" fontSize="22">
          Agent Knowledge Surfaces
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Three knowledge surfaces flow from bundle → loader → runtime catalog
          → chat-route consumer. All three feed the same chat handler at turn
          time.
        </text>

        {COLUMNS.map((c, ci) => {
          const x = colX(ci);
          const stepX = x + (COL_W - STEP_W) / 2;
          const firstStepY = COL_TOP + STEPS_TOP_OFFSET;
          return (
            <g key={c.id}>
              <rect
                className="col-bg"
                x={x}
                y={COL_TOP - 70}
                width={COL_W}
                height={COL_H}
                rx="18"
              />
              <text className="col-title" x={x + 24} y={COL_TOP - 36}>
                {c.title}
              </text>
              <text className="col-sub" x={x + 24} y={COL_TOP - 16}>
                {c.sub}
              </text>

              {/* Vertical edges connecting steps */}
              {c.steps.slice(0, -1).map((_, si) => {
                const y1 = firstStepY + si * (STEP_H + STEP_GAP) + STEP_H;
                const y2 = firstStepY + (si + 1) * (STEP_H + STEP_GAP);
                return (
                  <line
                    key={`${ci}-e-${si}`}
                    className={`col-edge ${c.id}`}
                    x1={x + COL_W / 2}
                    y1={y1}
                    x2={x + COL_W / 2}
                    y2={y2}
                    markerEnd={`url(#dgm-arrow-${c.id === "tools" ? "compose" : c.id === "skills" ? "shared" : "external"})`}
                  />
                );
              })}

              {/* Step cards */}
              {c.steps.map((s, si) => {
                const y = firstStepY + si * (STEP_H + STEP_GAP);
                return (
                  <g key={`${ci}-s-${si}`}>
                    <rect
                      className={`step-card ${c.id}`}
                      x={stepX}
                      y={y}
                      width={STEP_W}
                      height={STEP_H}
                      rx="14"
                    />
                    <text
                      className={`step-tag ${c.id}`}
                      x={stepX + 18}
                      y={y + 22}
                    >
                      {s.tag}
                    </text>
                    <text
                      className="step-name"
                      x={stepX + 18}
                      y={y + 46}
                    >
                      {s.name}
                    </text>
                    <text
                      className="step-detail"
                      x={stepX + 18}
                      y={y + 64}
                    >
                      {s.detail}
                    </text>
                  </g>
                );
              })}

              {/* Bottom edge from last step to consumer */}
              {(() => {
                const lastY =
                  firstStepY + (c.steps.length - 1) * (STEP_H + STEP_GAP) + STEP_H;
                return (
                  <path
                    className={`feed-edge`}
                    d={`M ${x + COL_W / 2} ${lastY} V ${consumerTop - 4}`}
                    markerEnd="url(#dgm-arrow-operator)"
                  />
                );
              })()}
            </g>
          );
        })}

        {/* Consumer (chat-route) — bottom hero card spanning all columns */}
        {(() => {
          const consumerX = colX(0);
          const consumerW = colX(COLUMNS.length - 1) + COL_W - colX(0);
          return (
            <g>
              <rect
                className="consumer-card"
                x={consumerX}
                y={consumerTop}
                width={consumerW}
                height={consumerH}
                rx="18"
              />
              <text
                className="consumer-title"
                x={consumerX + 28}
                y={consumerTop + 38}
              >
                chat-route /api/chat
              </text>
              <text
                className="consumer-detail"
                x={consumerX + 28}
                y={consumerTop + 64}
              >
                model receives: tool catalog · injected skill bodies · KB
                retrieval results
              </text>
              <text
                className="consumer-detail"
                x={consumerX + 28}
                y={consumerTop + 86}
                fontSize="11"
                fill="var(--dgm-text-muted)"
              >
                tools dispatched on function_call · skills bias the model&apos;s
                choice · KBs answer conceptual questions
              </text>
            </g>
          );
        })()}

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
            All three are bundle-shipped
          </text>
          <text className="legend-text" x="220" y="4">
            edit-then-redeploy is the only authoring loop · skills volume seeded
            on first run · KBs source-hash deduped at boot · tool metadata
            denormalized into tool_call SSE events.
          </text>
        </g>
      </svg>
    </div>
  );
}
