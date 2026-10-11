/**
 * Jobs subsystem diagram — creation → schedule → dispatch → outputs.
 *
 * Visualizes the four moving parts of the jobs subsystem:
 *
 *   1. Two creation paths converge into one store
 *      - Manifest-declared: bundle/spark/manifest.yaml:jobs[] reconciled
 *        at boot. Manifest is the source of truth — editing + redeploy
 *        overwrites the runtime DB.
 *      - Operator-created: via /jobs/new UI → POST /api/agent/jobs.
 *        Lives only in the runtime DB; survives upgrades (volume).
 *
 *   2. Cron scheduler tick
 *      - Single in-process loop inside phantom-agent ticks every minute
 *      - Reads runtime job DB, finds matching cron expressions
 *      - Submits matching jobs to the dispatcher
 *
 *   3. Action dispatcher (the discriminator)
 *      - action.skill — invoke a registered skill with given args
 *      - action.chat  — open a new chat session, post a message, drain
 *      - action.tool  — call a single MCP tool with given args
 *      Each branch lands in the same audit-row writer + hook-firing
 *      sequence so observability is uniform regardless of action type.
 *
 *   4. Outputs
 *      - audit row (one per run): job_run_started + job_run_finished
 *        events visible in /observability/events
 *      - hook fires: RunStart pre-action, RunEnd post-action
 *      - notification (if bypass_approvals=false + run produced output)
 *
 * Layout: fan-in at top (2 creation paths) → 1 store → cron loop →
 * 3-way dispatch in middle → fan-out at bottom (3 output sinks).
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.jobs .create-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.jobs .create-card.manifest { stroke: var(--dgm-edge-shared); }
.dgm-root.jobs .create-card.operator { stroke: var(--dgm-edge-operator); }
.dgm-root.jobs .store-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.4;
}
.dgm-root.jobs .scheduler {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-state-info);
  stroke-width: 2.4;
}
.dgm-root.jobs .scheduler-glow {
  fill: var(--dgm-state-info);
  opacity: 0.10;
}
.dgm-root.jobs .action-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.6;
}
.dgm-root.jobs .action-card.skill { stroke: var(--dgm-state-success); }
.dgm-root.jobs .action-card.chat  { stroke: var(--dgm-edge-operator); }
.dgm-root.jobs .action-card.tool  { stroke: var(--dgm-edge-shared); }
.dgm-root.jobs .sink-card {
  fill: var(--dgm-sink-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.jobs .sink-card.audit { stroke: var(--dgm-edge-iap); }
.dgm-root.jobs .sink-card.hooks { stroke: var(--dgm-state-warn); }
.dgm-root.jobs .sink-card.notify { stroke: var(--dgm-edge-compose); }
.dgm-root.jobs .lane-bg {
  fill: var(--dgm-panel);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
  stroke-dasharray: 4 6;
}
.dgm-root.jobs .layer-tag {
  fill: var(--dgm-text-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
`;

export function JobsLifecycle() {
  return (
    <div className="dgm-root jobs">
      <style>{STYLES}</style>
      <svg
        viewBox="0 0 1200 780"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Jobs subsystem lifecycle: two creation paths converge into a runtime store, ticked by a cron scheduler, dispatched through three action types, producing audit + hooks + notification outputs"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        <text x="600" y="36" textAnchor="middle" className="title" fontSize="22">
          Jobs subsystem — creation → schedule → dispatch → outputs
        </text>
        <text x="600" y="60" textAnchor="middle" className="detail" fontSize="13">
          Two creation paths · single store · one scheduler · three action types · uniform outputs
        </text>

        {/* ── LAYER 1: Creation paths (top) ─────────────────────────── */}
        <text x="80" y="100" className="layer-tag">1. CREATION</text>

        {/* Manifest-declared */}
        <rect x="120" y="115" width="380" height="95" rx="10" className="create-card manifest" />
        <text x="310" y="142" textAnchor="middle" className="node-title-small">Manifest-declared</text>
        <text x="310" y="162" textAnchor="middle" className="detail" fontSize="11">
          bundles/spark/manifest.yaml :: jobs[]
        </text>
        <text x="310" y="180" textAnchor="middle" className="muted" fontSize="10">
          Reconciled at every MCP boot. Manifest is source-of-truth.
        </text>
        <text x="310" y="196" textAnchor="middle" className="muted" fontSize="10">
          Edit YAML + redeploy → overwrites runtime DB row.
        </text>

        {/* Operator-created */}
        <rect x="700" y="115" width="380" height="95" rx="10" className="create-card operator" />
        <text x="890" y="142" textAnchor="middle" className="node-title-small">Operator-created</text>
        <text x="890" y="162" textAnchor="middle" className="detail" fontSize="11">
          /jobs/new UI → POST /api/agent/jobs
        </text>
        <text x="890" y="180" textAnchor="middle" className="muted" fontSize="10">
          Form fields: name, cron, action type, args, bypass_approvals.
        </text>
        <text x="890" y="196" textAnchor="middle" className="muted" fontSize="10">
          Lives in runtime DB only; survives image upgrades (volume).
        </text>

        {/* Arrows from creation → store */}
        <path className="edge muted" d="M 310 210 L 310 250 L 540 250 L 540 285" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 890 210 L 890 250 L 660 250 L 660 285" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 2: Runtime store ────────────────────────────────── */}
        <text x="80" y="270" className="layer-tag">2. STORE</text>
        <rect x="450" y="285" width="300" height="60" rx="8" className="store-card" />
        <text x="600" y="312" textAnchor="middle" className="node-title-small">jobs.db (runtime SQLite)</text>
        <text x="600" y="330" textAnchor="middle" className="muted" fontSize="11">
          one row per job: name · cron · action_type · args · enabled · last_run
        </text>

        {/* Arrow store → scheduler */}
        <path className="edge muted" d="M 600 345 L 600 385" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 3: Scheduler ────────────────────────────────────── */}
        <text x="80" y="375" className="layer-tag">3. SCHEDULER</text>
        <rect x="480" y="385" width="240" height="70" rx="8" className="scheduler-glow" />
        <rect x="480" y="385" width="240" height="70" rx="8" className="scheduler" />
        <text x="600" y="412" textAnchor="middle" className="node-title-small">Cron loop tick</text>
        <text x="600" y="432" textAnchor="middle" className="muted" fontSize="11">
          in-process inside phantom-agent · 1-min granularity
        </text>
        <text x="600" y="448" textAnchor="middle" className="muted" fontSize="10">
          reads jobs.db · matches cron exprs · submits to dispatcher
        </text>

        {/* Arrows scheduler → 3 actions */}
        <path className="edge muted" d="M 600 455 L 600 490 L 220 490 L 220 525" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 600 455 L 600 525" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 600 455 L 600 490 L 980 490 L 980 525" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 4: Action dispatch (3 types) ────────────────────── */}
        <text x="80" y="510" className="layer-tag">4. DISPATCH (action discriminator)</text>

        {/* action.skill */}
        <rect x="80" y="525" width="280" height="100" rx="10" className="action-card skill" />
        <text x="220" y="552" textAnchor="middle" className="node-title-small">action.skill</text>
        <text x="220" y="572" textAnchor="middle" className="muted" fontSize="11">
          invoke registered skill with args
        </text>
        <text x="220" y="592" textAnchor="middle" className="muted" fontSize="10">
          Skill loads its prompt + tools, runs to completion.
        </text>
        <text x="220" y="608" textAnchor="middle" className="muted" fontSize="10">
          Most common (recurring detection / reporting tasks).
        </text>

        {/* action.chat */}
        <rect x="460" y="525" width="280" height="100" rx="10" className="action-card chat" />
        <text x="600" y="552" textAnchor="middle" className="node-title-small">action.chat</text>
        <text x="600" y="572" textAnchor="middle" className="muted" fontSize="11">
          open chat session, post message, drain
        </text>
        <text x="600" y="592" textAnchor="middle" className="muted" fontSize="10">
          Like an operator typing a prompt. Agent decides which
        </text>
        <text x="600" y="608" textAnchor="middle" className="muted" fontSize="10">
          tools to call. Useful for free-form recurring queries.
        </text>

        {/* action.tool */}
        <rect x="840" y="525" width="280" height="100" rx="10" className="action-card tool" />
        <text x="980" y="552" textAnchor="middle" className="node-title-small">action.tool</text>
        <text x="980" y="572" textAnchor="middle" className="muted" fontSize="11">
          call one MCP tool with given args
        </text>
        <text x="980" y="592" textAnchor="middle" className="muted" fontSize="10">
          Direct tool dispatch (no LLM in the loop).
        </text>
        <text x="980" y="608" textAnchor="middle" className="muted" fontSize="10">
          Cheap + deterministic for known-good operations.
        </text>

        {/* Arrows action → outputs */}
        <path className="edge muted" d="M 220 625 L 220 660 L 220 700" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 600 625 L 600 660 L 600 700" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 980 625 L 980 660 L 980 700" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 5: Outputs (3 sinks) ────────────────────────────── */}
        <text x="80" y="685" className="layer-tag">5. OUTPUTS (uniform across action types)</text>

        <rect x="80" y="700" width="280" height="62" rx="8" className="sink-card audit" />
        <text x="220" y="722" textAnchor="middle" className="node-title-small">audit row</text>
        <text x="220" y="740" textAnchor="middle" className="muted" fontSize="10">
          job_run_started + job_run_finished events
        </text>
        <text x="220" y="754" textAnchor="middle" className="muted" fontSize="10">
          Visible in /observability/events
        </text>

        <rect x="460" y="700" width="280" height="62" rx="8" className="sink-card hooks" />
        <text x="600" y="722" textAnchor="middle" className="node-title-small">hooks fire</text>
        <text x="600" y="740" textAnchor="middle" className="muted" fontSize="10">
          RunStart (pre-action) · RunEnd (post-action)
        </text>
        <text x="600" y="754" textAnchor="middle" className="muted" fontSize="10">
          e.g. cost-warn-over-budget reads RunEnd
        </text>

        <rect x="840" y="700" width="280" height="62" rx="8" className="sink-card notify" />
        <text x="980" y="722" textAnchor="middle" className="node-title-small">notification</text>
        <text x="980" y="740" textAnchor="middle" className="muted" fontSize="10">
          If output produced AND bypass_approvals=false:
        </text>
        <text x="980" y="754" textAnchor="middle" className="muted" fontSize="10">
          row in /notifications + sidebar badge increment
        </text>
      </svg>
    </div>
  );
}
