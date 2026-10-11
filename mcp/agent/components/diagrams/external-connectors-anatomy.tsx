"use client";

/**
 * Phantom External Connectors Anatomy.
 *
 * Three connector backends shown side-by-side, each as a card with:
 * protocol · port · auth header · tool family · sample call. Below
 * the cards: the synthetic-log pipeline showing how xlog feeds the
 * downstream webhook receiver, CALDERA emits operation results, and
 * XSIAM returns XQL query rows.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.exc .conn-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-stroke-strong);
  stroke-width: 1.6;
}
.dgm-root.exc .conn-card.xlog { stroke: var(--dgm-edge-compose); }
.dgm-root.exc .conn-card.caldera { stroke: var(--dgm-edge-compose); }
.dgm-root.exc .conn-card.xsiam { stroke: var(--dgm-edge-external); }
.dgm-root.exc .conn-name {
  fill: var(--dgm-text-main);
  font-size: 22px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.exc .conn-tagline {
  fill: var(--dgm-text-soft);
  font-size: 12px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.exc .field-label {
  fill: var(--dgm-text-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}
.dgm-root.exc .field-value {
  fill: var(--dgm-text-main);
  font-size: 12.5px;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.exc .tool-pill {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
}
.dgm-root.exc .tool-pill.xlog { stroke: var(--dgm-edge-compose); }
.dgm-root.exc .tool-pill.caldera { stroke: var(--dgm-edge-compose); }
.dgm-root.exc .tool-pill.xsiam { stroke: var(--dgm-edge-external); }
.dgm-root.exc .tool-pill-text {
  font-size: 10.5px;
  font-weight: 600;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.exc .tool-pill-text.xlog { fill: var(--dgm-edge-compose); }
.dgm-root.exc .tool-pill-text.caldera { fill: var(--dgm-edge-compose); }
.dgm-root.exc .tool-pill-text.xsiam { fill: var(--dgm-edge-external); }
.dgm-root.exc .pipeline-card {
  fill: var(--dgm-bg-1);
  stroke: var(--dgm-stroke-muted);
}
.dgm-root.exc .pipe-step {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.exc .pipe-step-text {
  fill: var(--dgm-text-main);
  font-size: 12px;
  font-weight: 600;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.exc .pipe-edge {
  stroke: var(--dgm-edge-compose);
  stroke-width: 1.6;
  fill: none;
}
.dgm-root.exc .pipe-edge.external {
  stroke: var(--dgm-edge-external);
}
`;

interface Connector {
  id: "xlog" | "caldera" | "xsiam";
  name: string;
  tagline: string;
  protocol: string;
  port: string;
  auth: string;
  authValue: string;
  toolPrefix: string;
  toolCount: string;
  sampleTool: string;
  tools: string[];
}

const CONNECTORS: Connector[] = [
  {
    id: "xlog",
    name: "xlog",
    tagline: "synthetic security telemetry",
    protocol: "GraphQL",
    port: "compose-internal :8000",
    auth: "AUTH",
    authValue: "no wire auth (internal)",
    toolPrefix: "xlog.*",
    toolCount: "~25 tools",
    sampleTool: "xlog.create_scenario_worker",
    tools: [
      "list_workers",
      "create_worker",
      "create_scenario_worker",
      "stop_worker",
      "list_scenarios",
      "send_observable",
    ],
  },
  {
    id: "caldera",
    name: "caldera",
    tagline: "MITRE ATT&CK adversary emulation",
    protocol: "REST",
    port: "compose-internal :8888",
    auth: "AUTH",
    authValue: "red-user + api_key",
    toolPrefix: "caldera.*",
    toolCount: "~20 tools",
    sampleTool: "caldera.start_operation",
    tools: [
      "list_abilities",
      "list_adversaries",
      "list_agents",
      "start_operation",
      "get_results",
      "kill_operation",
    ],
  },
  {
    id: "xsiam",
    name: "XSIAM PAPI",
    tagline: "Cortex Cloud · external SaaS",
    protocol: "HTTPS",
    port: "tenant.paloaltonetworks.com",
    auth: "AUTH",
    authValue: "x-xdr-auth-id + bearer",
    toolPrefix: "xsiam.*",
    toolCount: "~30 tools",
    sampleTool: "xsiam.run_xql",
    tools: [
      "run_xql",
      "find_xql_examples_rag",
      "list_detection_rules",
      "get_rule",
      "upsert_rule",
      "list_issues",
    ],
  },
];

const VIEW_W = 1520;
const VIEW_H = 1080;

const CARD_W = 460;
const CARD_H = 480;
const CARD_GAP = 30;
const CARD_TOP = 130;

const PIPE_TOP = CARD_TOP + CARD_H + 80;
const PIPE_H = 200;

export function ExternalConnectorsAnatomy() {
  const totalW = CONNECTORS.length * CARD_W + (CONNECTORS.length - 1) * CARD_GAP;
  const startX = (VIEW_W - totalW) / 2;
  const cardX = (i: number) => startX + i * (CARD_W + CARD_GAP);

  return (
    <div className="dgm-root exc">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="exc-title exc-desc"
      >
        <title id="exc-title">External Connectors Anatomy</title>
        <desc id="exc-desc">
          xlog, CALDERA, and XSIAM PAPI side-by-side with their protocols,
          ports, auth, and tool families.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="exc-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#exc-dot-grid)" />

        <text x="60" y="44" className="title" fontSize="22">
          External Connectors Anatomy
        </text>
        <text x="60" y="68" className="detail" fontSize="13">
          Three connector backends each get a column: protocol, port, auth,
          tool family. Bottom band traces the synthetic-log pipeline.
        </text>

        {/* Connector cards */}
        {CONNECTORS.map((c, i) => {
          const x = cardX(i);
          return (
            <g key={c.id}>
              <rect
                className={`conn-card ${c.id}`}
                x={x}
                y={CARD_TOP}
                width={CARD_W}
                height={CARD_H}
                rx="18"
              />
              <text className="conn-name" x={x + 28} y={CARD_TOP + 44}>
                {c.name}
              </text>
              <text className="conn-tagline" x={x + 28} y={CARD_TOP + 66}>
                {c.tagline}
              </text>

              {/* Field rows */}
              {[
                { label: "PROTOCOL", value: c.protocol },
                { label: "ENDPOINT", value: c.port },
                { label: "AUTH", value: c.authValue },
                { label: "TOOL PREFIX", value: `${c.toolPrefix}  ·  ${c.toolCount}` },
                { label: "EXAMPLE CALL", value: c.sampleTool },
              ].map((row, ri) => {
                const ry = CARD_TOP + 110 + ri * 38;
                return (
                  <g key={row.label}>
                    <text
                      className="field-label"
                      x={x + 28}
                      y={ry}
                    >
                      {row.label}
                    </text>
                    <text
                      className="field-value"
                      x={x + 28}
                      y={ry + 18}
                    >
                      {row.value}
                    </text>
                  </g>
                );
              })}

              {/* Tool pills */}
              <text
                className="field-label"
                x={x + 28}
                y={CARD_TOP + 320}
              >
                TOOLS (sample)
              </text>
              {c.tools.map((t, ti) => {
                const col = ti % 2;
                const row = Math.floor(ti / 2);
                const px = x + 28 + col * 200;
                const py = CARD_TOP + 340 + row * 32;
                return (
                  <g key={t}>
                    <rect
                      className={`tool-pill ${c.id}`}
                      x={px}
                      y={py}
                      width="186"
                      height="22"
                      rx="6"
                    />
                    <text
                      className={`tool-pill-text ${c.id}`}
                      x={px + 12}
                      y={py + 15}
                    >
                      {t}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* Synthetic-log pipeline (bottom strip) — only meaningful for xlog */}
        <g>
          <rect
            className="pipeline-card"
            x={cardX(0)}
            y={PIPE_TOP - 30}
            width={cardX(2) + CARD_W - cardX(0)}
            height={PIPE_H}
            rx="18"
          />
          <text
            className="lane-label"
            x={cardX(0) + 24}
            y={PIPE_TOP - 8}
            fontSize="11"
          >
            SYNTHETIC-LOG PIPELINE (xlog → webhook)
          </text>

          {/* Pipeline steps */}
          {[
            { name: "scenario JSON", detail: "scenarios/ready/*.json" },
            { name: "worker spawn", detail: "module-level dict + thread" },
            { name: "rosetta-ce events", detail: "vendor-shaped log lines" },
            { name: "sender", detail: "UDP / HTTPS webhook / collector" },
            { name: "receiver", detail: "XSIAM HTTP collector / arbitrary" },
          ].map((s, si, all) => {
            const stepW = 240;
            const totalSteps = all.length;
            const totalStepsW = totalSteps * stepW;
            const totalGap = (cardX(2) + CARD_W - cardX(0) - 60 - totalStepsW);
            const gap = totalGap / (totalSteps - 1);
            const px = cardX(0) + 30 + si * (stepW + gap);
            const py = PIPE_TOP + 30;
            return (
              <g key={s.name}>
                <rect
                  className="pipe-step"
                  x={px}
                  y={py}
                  width={stepW}
                  height="64"
                  rx="12"
                />
                <text className="pipe-step-text" x={px + 14} y={py + 24}>
                  {s.name}
                </text>
                <text
                  className="step-detail"
                  x={px + 14}
                  y={py + 46}
                  fontSize="11"
                  fill="var(--dgm-text-soft)"
                  fontFamily='"JetBrains Mono", "SFMono-Regular", monospace'
                >
                  {s.detail}
                </text>
                {si < totalSteps - 1 && (
                  <line
                    className={`pipe-edge ${si === totalSteps - 2 ? "external" : ""}`}
                    x1={px + stepW + 4}
                    y1={py + 32}
                    x2={px + stepW + gap - 4}
                    y2={py + 32}
                    markerEnd={`url(#dgm-arrow-${si === totalSteps - 2 ? "external" : "compose"})`}
                  />
                )}
              </g>
            );
          })}
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
            Why three columns?
          </text>
          <text className="legend-text" x="180" y="4">
            xlog and CALDERA run inside the Compose network (green); XSIAM is
            external SaaS (orange). All three present the same shape — a
            namespaced tool family the agent invokes via function_call.
          </text>
        </g>
      </svg>
    </div>
  );
}
