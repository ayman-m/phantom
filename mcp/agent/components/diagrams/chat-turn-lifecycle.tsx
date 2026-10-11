"use client";

/**
 * Phantom Chat Turn Lifecycle — sequence diagram of one chat turn.
 *
 * Visualises the 12 numbered steps the chat-route handler runs for
 * every turn, mapped across 4 swim lanes (browser · agent · MCP ·
 * model). Hook fire-sites appear as flag markers on the left margin
 * at the steps where they fire; representative SSE events stream
 * back leftward to the browser as small chips.
 *
 * Colour tokens come from the shared _diagram-theme; layout and
 * step-flag positioning live here.
 *
 * No animations. No JavaScript. Pure SVG + CSS.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.ctl .lane-stripe {
  fill: var(--dgm-bg-1);
  opacity: 0.45;
}
.dgm-root.ctl .lane-divider {
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
  stroke-dasharray: 4 6;
}
.dgm-root.ctl .step-badge {
  fill: var(--dgm-edge-shared);
  stroke: var(--dgm-bg-0);
  stroke-width: 2;
}
.dgm-root.ctl .step-badge-text {
  fill: var(--dgm-bg-0);
  font-size: 12px;
  font-weight: 800;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.ctl .step-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.2;
}
.dgm-root.ctl .step-card.gated {
  stroke: var(--dgm-edge-shared);
  stroke-width: 1.6;
}
.dgm-root.ctl .step-card.tool {
  stroke: var(--dgm-edge-compose);
  stroke-width: 1.6;
}
.dgm-root.ctl .step-card.model {
  stroke: var(--dgm-edge-external);
  stroke-width: 1.6;
}
.dgm-root.ctl .step-title {
  font-size: 13.5px;
  font-weight: 700;
  fill: var(--dgm-text-main);
  letter-spacing: -0.005em;
}
.dgm-root.ctl .step-detail {
  font-size: 11.5px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.ctl .hook-flag {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-edge-iap);
  stroke-width: 1;
}
.dgm-root.ctl .hook-flag-text {
  fill: var(--dgm-text-soft);
  font-size: 10.5px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.ctl .sse-chip {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-edge-operator);
  stroke-width: 1;
}
.dgm-root.ctl .sse-chip-text {
  fill: var(--dgm-edge-operator);
  font-size: 10.5px;
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.ctl .lane-header-bg {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
}
.dgm-root.ctl .lane-header-text {
  fill: var(--dgm-text-main);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.06em;
}
.dgm-root.ctl .lane-header-icon {
  fill: none;
  stroke: var(--dgm-text-main);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
`;

/** Numbered step flowing top-to-bottom in one of the 4 lanes. */
interface Step {
  n: number;
  /** which lane: 0=browser, 1=agent, 2=mcp, 3=model */
  lane: 0 | 1 | 2 | 3;
  title: string;
  detail: string;
  /** semantic emphasis — gated (approval), tool (compose-internal), model (external) */
  variant?: "default" | "gated" | "tool" | "model";
  /** SSE event(s) emitted to the browser at this step */
  sse?: string[];
  /** Hook fire-site at this step */
  hook?: string;
}

const STEPS: Step[] = [
  {
    n: 1,
    lane: 0,
    title: "Operator submits prompt",
    detail: "POST /api/chat { sid, prompt }",
    sse: ["session"],
  },
  {
    n: 2,
    lane: 1,
    title: "Persist user message",
    detail: "safePersist(role:'user', …)",
    hook: "UserPromptSubmit",
  },
  {
    n: 3,
    lane: 1,
    title: "Resolve model",
    detail: "header → session → workspace → bundle",
    sse: ["model"],
  },
  {
    n: 4,
    lane: 1,
    title: "Load history (token-aware)",
    detail: "newest→oldest walk; auto-compact",
    hook: "PreCompact",
    sse: ["compaction_start", "compaction_end"],
  },
  {
    n: 5,
    lane: 1,
    title: "Context-window guard",
    detail: ">90%: warn · >99%: block",
    sse: ["context_warning"],
  },
  {
    n: 6,
    lane: 3,
    title: "Initial Gemini call",
    detail: "callGemini(history, tools)",
    variant: "model",
    sse: ["text_delta", "cache_hit"],
  },
  {
    n: 7,
    lane: 1,
    title: "Tool-call decision",
    detail: "function_call → dispatch loop",
  },
  {
    n: 8,
    lane: 2,
    title: "PreToolUse + tier gate",
    detail: "tier 2/3: enqueue + await approval",
    variant: "gated",
    hook: "PreToolUse",
    sse: ["tool_call", "approval_required"],
  },
  {
    n: 9,
    lane: 2,
    title: "Dispatch tool",
    detail: "MCP routes; updates connector_state",
    variant: "tool",
    sse: ["tool_result"],
  },
  {
    n: 10,
    lane: 2,
    title: "PostToolUse + audit",
    detail: "safeAudit(tool_call, target, status)",
    hook: "PostToolUse",
  },
  {
    n: 11,
    lane: 3,
    title: "Continuation Gemini call",
    detail: "loop 6→10 until final text",
    variant: "model",
    sse: ["text_delta"],
  },
  {
    n: 12,
    lane: 1,
    title: "Persist assistant + cost row",
    detail: "extractAndRecordCost · safeAudit",
    hook: "Stop",
    sse: ["cost", "done"],
  },
];

// ── Layout constants ─────────────────────────────────────────────
// Three columns (left → right): hook-flags · 4 lane swim lanes · sse-chips.
// VIEW_W is tall enough for header + 12 steps + footer legend without
// clipping; lane-3 right edge stays clear of SSE_CHIP_X by ≥ 20px.
const VIEW_W = 1520;
const VIEW_H = 1340;
const LANE_LEFT = 235; // x where lanes start
const LANE_WIDTH = 235; // each lane's width
const LANE_GAP = 14; // gap between lanes
const HEADER_Y = 80; // y of lane header band
const HEADER_H = 50;
const FIRST_STEP_Y = 175; // y of first step
const STEP_GAP = 84; // vertical gap between steps
const STEP_W = 210;
const STEP_H = 64;
const HOOK_FLAG_X = 30; // x of hook flag column
const HOOK_FLAG_W = 180;
const SSE_CHIP_X = 1240; // x of SSE chip column (≥ lane-3 right edge + 20)
const SSE_CHIP_W = 150;

const laneX = (lane: number) => LANE_LEFT + lane * (LANE_WIDTH + LANE_GAP);
const stepCardX = (lane: number) => laneX(lane) + (LANE_WIDTH - STEP_W) / 2;
const stepY = (n: number) => FIRST_STEP_Y + (n - 1) * STEP_GAP;

const LANES = [
  {
    name: "Browser",
    sub: "operator UI",
    iconPath: (
      <g>
        <rect x="-9" y="-7" width="18" height="14" rx="2" />
        <line x1="-9" y1="-3" x2="9" y2="-3" />
      </g>
    ),
  },
  {
    name: "phantom-agent",
    sub: "Next.js · :3000",
    iconPath: (
      <polyline points="2,-9 -4,2 1,2 -2,9 4,-2 -1,-2 2,-9" />
    ),
  },
  {
    name: "phantom-mcp",
    sub: "FastMCP · :8080",
    iconPath: (
      <g>
        <circle cx="0" cy="0" r="2.5" />
        <circle cx="-7" cy="-5" r="2" />
        <circle cx="7" cy="-5" r="2" />
        <circle cx="-7" cy="5" r="2" />
        <circle cx="7" cy="5" r="2" />
        <line x1="-1.5" y1="-1.2" x2="-5.6" y2="-4.2" />
        <line x1="1.5" y1="-1.2" x2="5.6" y2="-4.2" />
        <line x1="-1.5" y1="1.2" x2="-5.6" y2="4.2" />
        <line x1="1.5" y1="1.2" x2="5.6" y2="4.2" />
      </g>
    ),
  },
  {
    name: "Vertex / Gemini",
    sub: "external · model",
    iconPath: (
      <path d="M0,-10 L2.5,-2.5 L10,0 L2.5,2.5 L0,10 L-2.5,2.5 L-10,0 L-2.5,-2.5 Z" />
    ),
  },
];

export function ChatTurnLifecycle() {
  return (
    <div className="dgm-root ctl">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-labelledby="ctl-diagram-title ctl-diagram-desc"
      >
        <title id="ctl-diagram-title">Chat turn lifecycle</title>
        <desc id="ctl-diagram-desc">
          Sequence diagram of the 12 steps the chat-route handler runs
          for every chat turn, with hook fire-sites flagged on the
          left margin and representative SSE events emitted on the
          right.
        </desc>

        <defs>
          <DiagramMarkers />
          <pattern
            id="ctl-dot-grid"
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
          </pattern>
        </defs>

        {/* Background */}
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="var(--dgm-bg-0)" />
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#ctl-dot-grid)" />

        {/* Header */}
        <text x={LANE_LEFT} y={38} className="title" fontSize="22">
          Chat Turn Lifecycle
        </text>
        <text x={LANE_LEFT} y={60} className="detail" fontSize="13">
          12 steps · 4 actors · hooks fire on the left · SSE events stream right
        </text>

        {/* Hook column header */}
        <text
          x={HOOK_FLAG_X}
          y={HEADER_Y + 32}
          className="lane-label"
          fontSize="11"
        >
          HOOK FIRE-SITES
        </text>

        {/* SSE column header */}
        <text
          x={SSE_CHIP_X}
          y={HEADER_Y + 32}
          className="lane-label"
          fontSize="11"
        >
          SSE EVENTS
        </text>

        {/* Lane headers + stripes */}
        {LANES.map((lane, i) => {
          const x = laneX(i);
          return (
            <g key={i}>
              <rect
                className="lane-stripe"
                x={x - 6}
                y={HEADER_Y + HEADER_H + 6}
                width={LANE_WIDTH + 12}
                height={STEP_GAP * STEPS.length + 30}
                rx="14"
              />
              <line
                className="lane-divider"
                x1={x + LANE_WIDTH / 2}
                y1={HEADER_Y + HEADER_H + 12}
                x2={x + LANE_WIDTH / 2}
                y2={HEADER_Y + HEADER_H + STEP_GAP * STEPS.length + 30}
              />
              <rect
                className="lane-header-bg"
                x={x}
                y={HEADER_Y}
                width={LANE_WIDTH}
                height={HEADER_H}
                rx="12"
              />
              <g
                transform={`translate(${x + 24} ${HEADER_Y + HEADER_H / 2})`}
                className="lane-header-icon"
              >
                {lane.iconPath}
              </g>
              <text
                x={x + 50}
                y={HEADER_Y + 22}
                className="lane-header-text"
              >
                {lane.name}
              </text>
              <text
                x={x + 50}
                y={HEADER_Y + 38}
                className="node-subtitle"
                fontSize="11"
              >
                {lane.sub}
              </text>
            </g>
          );
        })}

        {/* Steps + connectors between sequential steps */}
        {STEPS.map((step, idx) => {
          const cx = stepCardX(step.lane) + STEP_W / 2;
          const cy = stepY(step.n) + STEP_H / 2;
          const cardClass = `step-card ${step.variant ?? "default"}`;

          // Connector to previous step (if any) — vertical or curved
          const prev = idx > 0 ? STEPS[idx - 1] : null;
          let connector: React.ReactNode = null;
          if (prev) {
            const prevCx = stepCardX(prev.lane) + STEP_W / 2;
            const prevBottomY = stepY(prev.n) + STEP_H;
            const thisTopY = stepY(step.n);
            const sameLane = prev.lane === step.lane;
            const edgeClass =
              step.variant === "gated"
                ? "edge shared"
                : step.variant === "tool"
                  ? "edge compose"
                  : step.variant === "model"
                    ? "edge external"
                    : "edge operator";
            if (sameLane) {
              connector = (
                <path
                  className={edgeClass}
                  d={`M ${prevCx} ${prevBottomY} L ${cx} ${thisTopY}`}
                />
              );
            } else {
              // Orthogonal routing reads better than a Bezier curve for
              // sequence-diagram cross-lane jumps. V→H→V with a small
              // rounded corner at each elbow.
              const midY = (prevBottomY + thisTopY) / 2;
              const r = 8; // corner radius
              const dir = cx > prevCx ? 1 : -1;
              connector = (
                <path
                  className={edgeClass}
                  d={
                    `M ${prevCx} ${prevBottomY} ` +
                    `V ${midY - r} ` +
                    `Q ${prevCx} ${midY} ${prevCx + dir * r} ${midY} ` +
                    `H ${cx - dir * r} ` +
                    `Q ${cx} ${midY} ${cx} ${midY + r} ` +
                    `V ${thisTopY}`
                  }
                />
              );
            }
          }

          return (
            <g key={step.n}>
              {connector}
              {/* Hook flag on the left */}
              {step.hook && (
                <g>
                  <rect
                    className="hook-flag"
                    x={HOOK_FLAG_X}
                    y={cy - 12}
                    width={HOOK_FLAG_W}
                    height={24}
                    rx="6"
                  />
                  <text
                    className="hook-flag-text"
                    x={HOOK_FLAG_X + 10}
                    y={cy + 4}
                  >
                    {step.hook}
                  </text>
                  {/* Connector dash from flag to step */}
                  <line
                    x1={HOOK_FLAG_X + HOOK_FLAG_W}
                    y1={cy}
                    x2={stepCardX(step.lane) - 4}
                    y2={cy}
                    stroke="var(--dgm-edge-iap)"
                    strokeWidth="1"
                    strokeDasharray="3 4"
                  />
                </g>
              )}

              {/* Step card */}
              <rect
                className={cardClass}
                x={stepCardX(step.lane)}
                y={stepY(step.n)}
                width={STEP_W}
                height={STEP_H}
                rx="10"
              />
              <text
                className="step-title"
                x={stepCardX(step.lane) + 38}
                y={stepY(step.n) + 24}
              >
                {step.title}
              </text>
              <text
                className="step-detail"
                x={stepCardX(step.lane) + 38}
                y={stepY(step.n) + 46}
              >
                {step.detail}
              </text>

              {/* Step number badge */}
              <circle
                className="step-badge"
                cx={stepCardX(step.lane) + 19}
                cy={stepY(step.n) + 32}
                r="13"
              />
              <text
                className="step-badge-text"
                x={stepCardX(step.lane) + 19}
                y={stepY(step.n) + 36}
                textAnchor="middle"
              >
                {String(step.n).padStart(2, "0")}
              </text>

              {/* SSE chips on the right */}
              {step.sse?.map((evt, i) => (
                <g
                  key={i}
                  transform={`translate(${SSE_CHIP_X} ${cy - 12 + i * 22})`}
                >
                  <rect
                    className="sse-chip"
                    width={SSE_CHIP_W}
                    height={20}
                    rx="6"
                  />
                  <text className="sse-chip-text" x="10" y="14">
                    {evt}
                  </text>
                </g>
              ))}
              {/* Connector dash from step to first SSE chip */}
              {step.sse && step.sse.length > 0 && (
                <line
                  x1={stepCardX(step.lane) + STEP_W + 4}
                  y1={cy}
                  x2={SSE_CHIP_X - 4}
                  y2={cy}
                  stroke="var(--dgm-edge-operator)"
                  strokeWidth="1"
                  strokeDasharray="3 4"
                />
              )}
            </g>
          );
        })}

        {/* Footer legend */}
        <g transform={`translate(${LANE_LEFT} ${VIEW_H - 70})`}>
          <rect
            x="0"
            y="-18"
            width="940"
            height="54"
            rx="14"
            fill="var(--dgm-panel)"
            stroke="var(--dgm-stroke-muted)"
          />
          <text className="legend-title" x="18" y="4">
            Step variant
          </text>

          <line
            className="legend-line"
            x1="120"
            y1="0"
            x2="156"
            y2="0"
            stroke="var(--dgm-edge-operator)"
          />
          <text className="legend-text" x="166" y="4">
            agent-internal
          </text>

          <line
            className="legend-line"
            x1="312"
            y1="0"
            x2="348"
            y2="0"
            stroke="var(--dgm-edge-shared)"
            strokeWidth="4"
          />
          <text className="legend-text" x="358" y="4">
            tier-gated (approval)
          </text>

          <line
            className="legend-line"
            x1="540"
            y1="0"
            x2="576"
            y2="0"
            stroke="var(--dgm-edge-compose)"
          />
          <text className="legend-text" x="586" y="4">
            tool dispatch
          </text>

          <line
            className="legend-line"
            x1="720"
            y1="0"
            x2="756"
            y2="0"
            stroke="var(--dgm-edge-external)"
          />
          <text className="legend-text" x="766" y="4">
            model (external)
          </text>

          <text className="legend-text" x="18" y="26" fontSize="11">
            Hook fire-sites flag the chat-route lifecycle event that triggers
            them; SSE events show what streams back to the browser.
          </text>
        </g>
      </svg>
    </div>
  );
}
