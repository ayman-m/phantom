/**
 * Pre-compact context-usage warning.
 *
 * Fires on the `PreCompact` event right before the chat-route's
 * auto-compaction strips early conversation context. Posts a
 * notification (severity: info) so the operator gets a heads-up
 * BEFORE compaction destroys the early history. Without this hook
 * auto-compaction is silent, and an operator could discover only
 * afterwards that a long analysis session was summarized to a few
 * bullets.
 *
 * Config:
 *   threshold_pct        — only fire when context is at least this
 *                          full (default 80; min 50, max 95). Lower
 *                          numbers = earlier warning + more noise.
 *   suppress_repeat_minutes — don't re-fire if this session was
 *                          warned within this many minutes (default
 *                          5). Prevents banner-spam during a busy
 *                          turn cluster.
 *
 * The notification goes to the fixed `context-warning` topic (declared in
 * bundles/spark/manifest.yaml). Older stored configs may still carry a
 * `notify_category` key; validateConfig drops it.
 *
 * Why a notification rather than a chat banner: notifications are the
 * existing operator-attention surface; banners would require a new
 * SSE event type the UI subscribes to. The notification path needs
 * no UI changes.
 *
 * In-memory suppression: keeps a per-session "last warned at" map so
 * the suppress_repeat_minutes window enforces. The map is per-process
 * (lost on restart), which is fine — restarts are infrequent and
 * the worst case is one extra warning right after a restart.
 */

import type { BuiltinHookSpec } from "./types";
import { CONTEXT_WARNING_TOPIC } from "./notification-topics";
import { publishHookNotification } from "./publish-notification";

const SESSION_LAST_WARNED_AT = new Map<string, number>();

export const preCompactContextWarningBuiltin: BuiltinHookSpec = {
  name: "pre-compact-context-warning",
  displayName: "Pre-compact context warning",
  description:
    "Warns the operator (via /notifications) BEFORE the chat route's " +
    "auto-compaction strips early conversation context. Configurable " +
    "threshold + repeat-suppress window. Doesn't change compaction " +
    "behavior — just announces it.",
  icon: "warning",
  compatibleEvents: ["PreCompact"] as const,
  configFields: [
    {
      key: "threshold_pct",
      label: "Warning threshold (% of context window)",
      type: "number",
      min: 50,
      max: 95,
      defaultValue: 80,
      helper:
        "Fire only when context is at least this full. Lower = earlier " +
        "warning + more noise. PreCompact already only fires when " +
        "compaction is about to happen, so a low threshold mostly " +
        "controls whether the warning fires on near-misses.",
      required: false,
    },
    {
      key: "suppress_repeat_minutes",
      label: "Suppress repeats within (minutes)",
      type: "number",
      min: 0,
      max: 60,
      defaultValue: 5,
      helper:
        "Don't re-warn the same session within this window. Set 0 to " +
        "disable suppression (every PreCompact fires a notification).",
      required: false,
    },
  ] as const,
  validateConfig(raw) {
    if (raw && typeof raw !== "object") {
      return { ok: false, error: "config must be an object" };
    }
    const cfg = (raw ?? {}) as Record<string, unknown>;
    const out: Record<string, unknown> = {};

    const threshold = cfg.threshold_pct;
    if (threshold === undefined) {
      out.threshold_pct = 80;
    } else if (typeof threshold !== "number" || threshold < 50 || threshold > 95) {
      return {
        ok: false,
        error: "threshold_pct must be a number in [50, 95]",
      };
    } else {
      out.threshold_pct = threshold;
    }

    const repeat = cfg.suppress_repeat_minutes;
    if (repeat === undefined) {
      out.suppress_repeat_minutes = 5;
    } else if (typeof repeat !== "number" || repeat < 0 || repeat > 60) {
      return {
        ok: false,
        error: "suppress_repeat_minutes must be a number in [0, 60]",
      };
    } else {
      out.suppress_repeat_minutes = repeat;
    }

    // `notify_category` is not read: the topic is fixed. Hooks saved before
    // that field was removed still carry it, so it is ignored here (and so
    // absent from the stored config the next time the hook is saved).

    return { ok: true, config: out };
  },
  async handle(payload, config) {
    // The dispatcher only invokes us when event === "PreCompact"
    // (compatibleEvents enforces this on registration). Narrow
    // defensively all the same — TypeScript can't prove that here.
    if (payload.event !== "PreCompact") return null;
    const sessionId = payload.sessionId;
    const messageCount = payload.messageCount;

    // Suppression window: skip if we warned this session recently.
    const suppressMin = config.suppress_repeat_minutes as number;
    const lastWarned = SESSION_LAST_WARNED_AT.get(sessionId);
    const nowMs = Date.now();
    if (
      lastWarned !== undefined &&
      suppressMin > 0 &&
      nowMs - lastWarned < suppressMin * 60_000
    ) {
      return null; // No-op; the operator was warned recently.
    }

    // Publish the notification via MCP. Best-effort: a failure is logged
    // (never thrown) so the chat route's compaction proceeds either way.
    const published = await publishHookNotification(
      "pre-compact-context-warning",
      CONTEXT_WARNING_TOPIC,
      {
        severity: "info",
        title: "Chat context filling up — compaction imminent",
        body:
          `Session ${sessionId} is at ${payload.kind === "manual" ? "manual-compact" : "auto-compact"} ` +
          `threshold with ${messageCount} messages. Earlier turns ` +
          `will be summarized + replaced. Save anything you need ` +
          `to memory via the memory_store tool before continuing.`,
        session_id: sessionId,
        kind: payload.kind,
        message_count: messageCount,
        threshold_pct: config.threshold_pct,
      },
    );
    if (published) SESSION_LAST_WARNED_AT.set(sessionId, nowMs);

    // Non-decisional — the hook doesn't veto compaction, just warns.
    // (Could be extended later to allow `decision: 'deny'` for an
    // opt-in "never compact this session" mode.)
    return {};
  },
};
