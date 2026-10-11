"use client";

/**
 * Phantom auth flows — three animated diagrams.
 *
 * Visual argument: the SecretStore is the only place credentials live;
 * every auth journey converges on it. Each diagram below traces one
 * operator journey end-to-end (login, UI password change, CLI reset)
 * showing exactly which services touch SecretStore and in what order.
 *
 * Why three diagrams: operators need to see the auth path. The
 * contract is visual — if your installation deviates from one of
 * these flows, something's broken. Diagrams ARE the spec.
 *
 * Animations: SMIL <animateMotion> for the moving packet, CSS
 * @keyframes for node highlight pulses. Cycle: 10s, loops forever.
 * Reduced-motion users get a static layout (no movement, no pulse).
 *
 * Each diagram is exported separately so the architecture page can
 * place them in the single `#authentication` SubSection in the order
 * an operator encounters them: login → change-password → CLI reset.
 *
 * No legacy fallback paths are shown (there are none).
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

// ─────────────────────────────────────────────────────────────────
// Shared geometry + styles
// ─────────────────────────────────────────────────────────────────

const VIEW_W = 1180;
const VIEW_H = 520;

// 5 swim-lane columns positioned so 4-5 boxes can fit with breathing room.
const COL = {
  origin: 80, // Browser / Host shell
  edge: 320, // Next.js route / CLI
  store: 600, // SecretStore (hero — wider than others)
  audit: 920, // Audit log / Notification
};
const ROW_MAIN = 240; // vertical centerline for the hero row
const ROW_AUDIT = 110; // audit log sits above the main row
const ROW_NOTIFY = 380; // notification sits below the main row

const BOX = {
  w: 180,
  h: 100,
  storeW: 220, // SecretStore is wider (hero)
  storeH: 140,
};

const CYCLE_SECONDS = 10;

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.auth-flow .lane-band {
  fill: var(--dgm-panel);
}
.dgm-root.auth-flow .lane-tag {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  fill: var(--dgm-text-muted);
}
.dgm-root.auth-flow .node-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
  rx: 12;
}
.dgm-root.auth-flow .node-card.origin { stroke: var(--dgm-edge-operator); }
.dgm-root.auth-flow .node-card.edge { stroke: var(--dgm-state-info); }
.dgm-root.auth-flow .node-card.store {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.4;
}
.dgm-root.auth-flow .node-card.audit { stroke: var(--dgm-text-muted); }
.dgm-root.auth-flow .node-card.notify { stroke: var(--dgm-state-success); }
.dgm-root.auth-flow .node-card.host { stroke: var(--dgm-edge-iap); stroke-dasharray: 8 7; }

.dgm-root.auth-flow .node-title {
  font-size: 14px;
  font-weight: 760;
  fill: var(--dgm-text-main);
}
.dgm-root.auth-flow .node-sub {
  font-size: 10.5px;
  fill: var(--dgm-code);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-flow .node-detail {
  font-size: 10.5px;
  fill: var(--dgm-text-soft);
}
.dgm-root.auth-flow .store-title {
  font-size: 16px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-flow .store-key {
  font-size: 10.5px;
  fill: var(--dgm-edge-shared);
  font-weight: 700;
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-flow .store-detail {
  font-size: 10px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}

.dgm-root.auth-flow .arrow {
  fill: none;
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.6;
}
.dgm-root.auth-flow .arrow-flow {
  fill: none;
  stroke: var(--dgm-edge-operator);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-dasharray: 6 10;
  animation: dgm-flow ${CYCLE_SECONDS}s linear infinite;
}
.dgm-root.auth-flow .arrow-flow.compose { stroke: var(--dgm-edge-compose); }
.dgm-root.auth-flow .arrow-flow.shared { stroke: var(--dgm-edge-shared); }
.dgm-root.auth-flow .arrow-flow.warn { stroke: var(--dgm-state-warn); }
.dgm-root.auth-flow .arrow-flow.iap { stroke: var(--dgm-edge-iap); }

@keyframes dgm-flow {
  0% { stroke-dashoffset: 0; }
  100% { stroke-dashoffset: -160; }
}

.dgm-root.auth-flow .step-pill {
  fill: var(--dgm-bg-2);
  stroke: var(--dgm-stroke-strong);
  stroke-width: 1.2;
}
.dgm-root.auth-flow .step-num {
  font-size: 11px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-flow .step-label {
  font-size: 11px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}
.dgm-root.auth-flow .step-label-warn {
  fill: var(--dgm-state-warn);
  font-weight: 700;
}

.dgm-root.auth-flow .packet {
  fill: var(--dgm-edge-operator);
  stroke: var(--dgm-bg-0);
  stroke-width: 2;
}
.dgm-root.auth-flow .packet.compose { fill: var(--dgm-edge-compose); }
.dgm-root.auth-flow .packet.shared { fill: var(--dgm-edge-shared); }

.dgm-root.auth-flow .pulse-halo {
  fill: var(--dgm-edge-shared);
  opacity: 0;
  animation: dgm-pulse ${CYCLE_SECONDS}s ease-out infinite;
}
@keyframes dgm-pulse {
  0%, 100% { opacity: 0; transform: scale(1); }
  50% { opacity: 0.18; transform: scale(1.06); }
}

.dgm-root.auth-flow .legend-text {
  font-size: 11px;
  fill: var(--dgm-text-soft);
}
.dgm-root.auth-flow .diagram-title {
  font-size: 18px;
  font-weight: 800;
  fill: var(--dgm-text-main);
  letter-spacing: -0.01em;
}
.dgm-root.auth-flow .diagram-subtitle {
  font-size: 12px;
  fill: var(--dgm-text-soft);
  font-family: "JetBrains Mono", "SFMono-Regular", monospace;
}

@media (prefers-reduced-motion: reduce) {
  .dgm-root.auth-flow .arrow-flow { animation: none; }
  .dgm-root.auth-flow .pulse-halo { animation: none; }
  .dgm-root.auth-flow .packet-anim { display: none; }
}
`;

// ─────────────────────────────────────────────────────────────────
// Helpers — node, step, arrow primitives
// ─────────────────────────────────────────────────────────────────

interface NodeProps {
  x: number;
  y: number;
  w?: number;
  h?: number;
  variant: "origin" | "edge" | "store" | "audit" | "notify" | "host";
  title: string;
  sub?: string;
  detail?: string;
  isHero?: boolean;
}

function FlowNode({
  x,
  y,
  w = BOX.w,
  h = BOX.h,
  variant,
  title,
  sub,
  detail,
  isHero,
}: NodeProps) {
  const cx = x + w / 2;
  return (
    <g>
      {isHero && (
        <rect
          className="pulse-halo"
          x={x - 12}
          y={y - 12}
          width={w + 24}
          height={h + 24}
          rx={18}
          style={{ transformOrigin: `${cx}px ${y + h / 2}px` }}
        />
      )}
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
        y={y + 28}
        textAnchor="middle"
      >
        {title}
      </text>
      {sub && (
        <text
          className={variant === "store" ? "store-key" : "node-sub"}
          x={cx}
          y={y + 50}
          textAnchor="middle"
        >
          {sub}
        </text>
      )}
      {detail && (
        <text
          className={variant === "store" ? "store-detail" : "node-detail"}
          x={cx}
          y={y + 72}
          textAnchor="middle"
        >
          {detail}
        </text>
      )}
    </g>
  );
}

interface StepProps {
  num: number;
  x: number;
  y: number;
  label: string;
  warn?: boolean;
}

function StepBadge({ num, x, y, label, warn }: StepProps) {
  return (
    <g>
      <circle className="step-pill" cx={x} cy={y} r={11} />
      <text className="step-num" x={x} y={y + 4} textAnchor="middle">
        {num}
      </text>
      <text
        className={`step-label ${warn ? "step-label-warn" : ""}`}
        x={x + 18}
        y={y + 4}
      >
        {label}
      </text>
    </g>
  );
}

interface ArrowProps {
  from: { x: number; y: number };
  to: { x: number; y: number };
  variant?: "default" | "compose" | "shared" | "warn" | "iap";
  /** Animation start offset in seconds, used to sequence packets along
   *  multi-arrow flows so they appear to chain one-after-another. */
  delaySeconds: number;
  /** Packet duration in seconds. */
  durationSeconds?: number;
}

function FlowArrow({
  from,
  to,
  variant = "default",
  delaySeconds,
  durationSeconds = 1.6,
}: ArrowProps) {
  // Curved Bezier — control point pulled toward midpoint Y for a soft S.
  const midX = (from.x + to.x) / 2;
  const dy = to.y - from.y;
  const ctrl1 = { x: midX, y: from.y + dy * 0.05 };
  const ctrl2 = { x: midX, y: to.y - dy * 0.05 };
  const d = `M ${from.x} ${from.y} C ${ctrl1.x} ${ctrl1.y}, ${ctrl2.x} ${ctrl2.y}, ${to.x} ${to.y}`;
  const colorClass =
    variant === "default" ? "" : variant === "warn" ? "warn" : variant;
  const packetClass =
    variant === "default"
      ? ""
      : variant === "warn"
        ? "shared"
        : variant === "iap"
          ? "shared"
          : variant;
  return (
    <g>
      <path className="arrow" d={d} />
      <path className={`arrow-flow ${colorClass}`} d={d} />
      <circle className={`packet packet-anim ${packetClass}`} r={5}>
        <animateMotion
          dur={`${CYCLE_SECONDS}s`}
          begin={`${delaySeconds}s`}
          fill="freeze"
          repeatCount="indefinite"
          keyPoints={`0;1;1`}
          keyTimes={`0;${(durationSeconds / CYCLE_SECONDS).toFixed(3)};1`}
          calcMode="linear"
          path={d}
        />
      </circle>
    </g>
  );
}

// ─────────────────────────────────────────────────────────────────
// Diagram 1 — Login flow
// ─────────────────────────────────────────────────────────────────

export function AuthLoginFlow() {
  // 5 steps over 10s cycle, ~2s per step
  return (
    <div className="dgm-root auth-flow">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Login flow: browser → /api/auth/login → SecretStore verify → session token → cookie set"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        {/* Title strip */}
        <text className="diagram-title" x={40} y={36}>
          Login flow
        </text>
        <text className="diagram-subtitle" x={40} y={56}>
          POST /api/auth/login → SecretStore PBKDF2 verify → new session
          token → Set-Cookie
        </text>

        {/* Lane band — origin/edge/store/sinks visual grouping */}
        <rect
          className="lane-band"
          x={20}
          y={80}
          width={VIEW_W - 40}
          height={VIEW_H - 100}
          rx={16}
        />

        {/* Nodes */}
        <FlowNode
          x={COL.origin}
          y={ROW_MAIN}
          variant="origin"
          title="Browser"
          sub="https://phantom:3000"
          detail="admin / $PHANTOM_DEFAULT_ADMIN_PASSWORD"
        />
        <FlowNode
          x={COL.edge}
          y={ROW_MAIN}
          variant="edge"
          title="/api/auth/login"
          sub="Next.js route"
          detail="Rate-limit: 5/60s per IP"
        />
        <FlowNode
          x={COL.store}
          y={ROW_MAIN - 20}
          w={BOX.storeW}
          h={BOX.storeH}
          variant="store"
          title="SecretStore"
          sub="auth.v1"
          detail="PBKDF2-HMAC-SHA256 verify"
          isHero
        />
        <FlowNode
          x={COL.audit}
          y={ROW_AUDIT}
          variant="audit"
          title="Audit log"
          sub="action=login_success"
          detail="or login_failed"
        />
        <FlowNode
          x={COL.audit}
          y={ROW_NOTIFY}
          variant="notify"
          title="Set-Cookie"
          sub="phantom_session=<32B>"
          detail="HttpOnly · Secure · SameSite=Strict · Max-Age=7200"
        />

        {/* Arrows */}
        <FlowArrow
          from={{ x: COL.origin + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.edge, y: ROW_MAIN + BOX.h / 2 }}
          variant="default"
          delaySeconds={0}
          durationSeconds={1.8}
        />
        <FlowArrow
          from={{ x: COL.edge + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.store, y: ROW_MAIN + BOX.storeH / 2 - 20 }}
          variant="shared"
          delaySeconds={2}
          durationSeconds={1.8}
        />
        <FlowArrow
          from={{ x: COL.store + BOX.storeW, y: ROW_MAIN + BOX.storeH / 2 - 30 }}
          to={{ x: COL.audit, y: ROW_AUDIT + BOX.h / 2 }}
          variant="compose"
          delaySeconds={4}
          durationSeconds={1.8}
        />
        <FlowArrow
          from={{ x: COL.store + BOX.storeW, y: ROW_MAIN + BOX.storeH / 2 + 10 }}
          to={{ x: COL.audit, y: ROW_NOTIFY + BOX.h / 2 }}
          variant="compose"
          delaySeconds={6}
          durationSeconds={1.8}
        />
        <FlowArrow
          from={{ x: COL.audit, y: ROW_NOTIFY + BOX.h / 2 }}
          to={{ x: COL.origin + BOX.w / 2, y: ROW_MAIN + BOX.h }}
          variant="default"
          delaySeconds={8}
          durationSeconds={1.8}
        />

        {/* Step legend */}
        <StepBadge
          num={1}
          x={50}
          y={VIEW_H - 30}
          label="POST { username, password }"
        />
        <StepBadge num={2} x={290} y={VIEW_H - 30} label="auth.v1.read()" />
        <StepBadge
          num={3}
          x={490}
          y={VIEW_H - 30}
          label="audit (login_success)"
        />
        <StepBadge num={4} x={720} y={VIEW_H - 30} label="mint session token" />
        <StepBadge num={5} x={970} y={VIEW_H - 30} label="Set-Cookie ↩" />
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Diagram 2 — UI password change (from /profile)
// ─────────────────────────────────────────────────────────────────

export function AuthChangePasswordFlow() {
  return (
    <div className="dgm-root auth-flow">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="UI password change flow: /profile → /api/auth/change-password → verify current → write new hash → revoke all sessions → audit + notification → force logout"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        <text className="diagram-title" x={40} y={36}>
          Change password (UI)
        </text>
        <text className="diagram-subtitle" x={40} y={56}>
          /profile → verify current → write new hash → revoke all sessions
          → audit + notify → 401 on any other tab
        </text>

        <rect
          className="lane-band"
          x={20}
          y={80}
          width={VIEW_W - 40}
          height={VIEW_H - 100}
          rx={16}
        />

        <FlowNode
          x={COL.origin}
          y={ROW_MAIN}
          variant="origin"
          title="/profile"
          sub="Operator form"
          detail="{ current, new, confirm }"
        />
        <FlowNode
          x={COL.edge}
          y={ROW_MAIN}
          variant="edge"
          title="/api/auth/change-password"
          sub="POST"
          detail="Verify current via PBKDF2"
        />
        <FlowNode
          x={COL.store}
          y={ROW_MAIN - 20}
          w={BOX.storeW}
          h={BOX.storeH}
          variant="store"
          title="SecretStore"
          sub="auth.v1"
          detail="write hash + sessions.revokeAll()"
          isHero
        />
        <FlowNode
          x={COL.audit}
          y={ROW_AUDIT}
          variant="audit"
          title="Audit log"
          sub="password_changed_ui"
          detail="actor=user:admin"
        />
        <FlowNode
          x={COL.audit}
          y={ROW_NOTIFY}
          variant="notify"
          title="Notifications"
          sub='"Your password was changed"'
          detail="topic=security · severity=info"
        />

        {/* 1. /profile → route */}
        <FlowArrow
          from={{ x: COL.origin + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.edge, y: ROW_MAIN + BOX.h / 2 }}
          variant="default"
          delaySeconds={0}
          durationSeconds={1.6}
        />
        {/* 2. route → SecretStore */}
        <FlowArrow
          from={{ x: COL.edge + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.store, y: ROW_MAIN + BOX.storeH / 2 - 20 }}
          variant="shared"
          delaySeconds={2}
          durationSeconds={1.6}
        />
        {/* 3. SecretStore → audit */}
        <FlowArrow
          from={{ x: COL.store + BOX.storeW, y: ROW_MAIN + BOX.storeH / 2 - 30 }}
          to={{ x: COL.audit, y: ROW_AUDIT + BOX.h / 2 }}
          variant="compose"
          delaySeconds={4}
          durationSeconds={1.6}
        />
        {/* 4. SecretStore → notification */}
        <FlowArrow
          from={{ x: COL.store + BOX.storeW, y: ROW_MAIN + BOX.storeH / 2 + 10 }}
          to={{ x: COL.audit, y: ROW_NOTIFY + BOX.h / 2 }}
          variant="compose"
          delaySeconds={6}
          durationSeconds={1.6}
        />
        {/* 5. route → browser (force logout) */}
        <FlowArrow
          from={{ x: COL.edge + BOX.w / 2, y: ROW_MAIN }}
          to={{ x: COL.origin + BOX.w / 2, y: ROW_MAIN }}
          variant="warn"
          delaySeconds={8}
          durationSeconds={1.6}
        />

        <StepBadge num={1} x={50} y={VIEW_H - 30} label="POST { current, new }" />
        <StepBadge
          num={2}
          x={280}
          y={VIEW_H - 30}
          label="verify + write + revokeAll"
        />
        <StepBadge num={3} x={540} y={VIEW_H - 30} label="audit" />
        <StepBadge num={4} x={660} y={VIEW_H - 30} label="notify" />
        <StepBadge
          num={5}
          x={780}
          y={VIEW_H - 30}
          label="200 + Clear-Cookie → re-login"
          warn
        />
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Diagram 3 — CLI reset (forgot-password path)
// ─────────────────────────────────────────────────────────────────

export function AuthCliResetFlow() {
  return (
    <div className="dgm-root auth-flow">
      <style>{STYLES}</style>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="CLI reset flow: host shell → docker exec → reset-admin.mjs → SecretStore overwrite → revoke all sessions → audit → operator restarts agent"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        <text className="diagram-title" x={40} y={36}>
          Reset admin password (CLI)
        </text>
        <text className="diagram-subtitle" x={40} y={56}>
          Forgot-password path · runs from the host · no old-password
          required (trust comes from docker exec access)
        </text>

        <rect
          className="lane-band"
          x={20}
          y={80}
          width={VIEW_W - 40}
          height={VIEW_H - 100}
          rx={16}
        />

        <FlowNode
          x={COL.origin}
          y={ROW_MAIN}
          variant="host"
          title="Host shell"
          sub="docker exec -it"
          detail='phantom_agent node …'
        />
        <FlowNode
          x={COL.edge}
          y={ROW_MAIN}
          variant="edge"
          title="reset-admin.mjs"
          sub="/app/cli"
          detail='Type RESET → new password'
        />
        <FlowNode
          x={COL.store}
          y={ROW_MAIN - 20}
          w={BOX.storeW}
          h={BOX.storeH}
          variant="store"
          title="SecretStore"
          sub="auth.v1"
          detail="overwrite hash + revokeAll() + flag=true"
          isHero
        />
        <FlowNode
          x={COL.audit}
          y={ROW_AUDIT}
          variant="audit"
          title="Audit log"
          sub="password_changed_cli"
          detail={`actor=cli:<hostname>`}
        />
        <FlowNode
          x={COL.audit}
          y={ROW_NOTIFY}
          variant="notify"
          title="Operator action"
          sub="docker compose restart"
          detail="phantom-agent  (in-memory invalidate)"
        />

        {/* 1. Host shell → CLI */}
        <FlowArrow
          from={{ x: COL.origin + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.edge, y: ROW_MAIN + BOX.h / 2 }}
          variant="iap"
          delaySeconds={0}
          durationSeconds={1.6}
        />
        {/* 2. CLI → SecretStore */}
        <FlowArrow
          from={{ x: COL.edge + BOX.w, y: ROW_MAIN + BOX.h / 2 }}
          to={{ x: COL.store, y: ROW_MAIN + BOX.storeH / 2 - 20 }}
          variant="shared"
          delaySeconds={2}
          durationSeconds={1.6}
        />
        {/* 3. SecretStore → audit */}
        <FlowArrow
          from={{ x: COL.store + BOX.storeW, y: ROW_MAIN + BOX.storeH / 2 - 30 }}
          to={{ x: COL.audit, y: ROW_AUDIT + BOX.h / 2 }}
          variant="compose"
          delaySeconds={4}
          durationSeconds={1.6}
        />
        {/* 4. CLI prints "restart hint" to terminal */}
        <FlowArrow
          from={{ x: COL.edge + BOX.w / 2, y: ROW_MAIN + BOX.h }}
          to={{ x: COL.audit, y: ROW_NOTIFY + BOX.h / 2 }}
          variant="warn"
          delaySeconds={6}
          durationSeconds={1.6}
        />
        {/* 5. operator triggers restart */}
        <FlowArrow
          from={{ x: COL.audit, y: ROW_NOTIFY + BOX.h / 2 }}
          to={{ x: COL.origin + BOX.w / 2, y: ROW_MAIN + BOX.h }}
          variant="warn"
          delaySeconds={8}
          durationSeconds={1.6}
        />

        <StepBadge num={1} x={50} y={VIEW_H - 30} label="docker exec" />
        <StepBadge num={2} x={190} y={VIEW_H - 30} label="RESET ceremony + prompt" />
        <StepBadge num={3} x={420} y={VIEW_H - 30} label="overwrite hash" />
        <StepBadge num={4} x={600} y={VIEW_H - 30} label="audit (cli)" />
        <StepBadge
          num={5}
          x={730}
          y={VIEW_H - 30}
          label="operator restarts agent container"
          warn
        />
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Convenience wrapper — renders all three stacked, used by the
// architecture page's #authentication SubSection.
// ─────────────────────────────────────────────────────────────────

export function AuthFlowsStack() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <AuthLoginFlow />
      <AuthChangePasswordFlow />
      <AuthCliResetFlow />
    </div>
  );
}
