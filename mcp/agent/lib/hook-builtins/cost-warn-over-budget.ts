/**
 * Cost warn over budget.
 *
 * A builtin hook that watches RunEnd, reads cumulative
 * `chat_turn_cost` audit rows for the day, and fires a notification
 * when the daily total crosses an operator-set threshold. It is a
 * budget alarm only; per-skill / per-job / per-instance attribution
 * is not tracked (the /observability/cost page groups by provider).
 *
 * Cost data source: the existing `chat_turn_cost` audit rows recorded
 * by the chat route on every turn. There is no dedicated cost table —
 * the hook reads the audit surface (`{events, count, total}`) and sums it
 * with lib/cost-rows.ts, the same reader the cost page and `/cost` use.
 *
 * A call to a model with no known price has a null cost. It is counted and
 * named in the notification, never added to the total as $0 or a guess, so
 * the total is a floor when any call was unpriced.
 *
 * Config:
 *   threshold_usd      — daily cost threshold (default $10.00). When
 *                        the cumulative cost since UTC midnight
 *                        exceeds this, a notification fires. 0 means
 *                        no threshold: the first turn of each window
 *                        fires regardless of cost.
 *   suppress_repeat_hours — re-warn cadence after a threshold crossing
 *                        (default 1 hour). Prevents the same daily
 *                        crossing from spamming every chat turn.
 *
 * The notification goes to the fixed `cost-warning` topic (declared in
 * bundles/spark/manifest.yaml). Older stored configs may still carry a
 * `notify_category` key; validateConfig drops it.
 */

import type { BuiltinHookSpec } from "./types";
import { callMcpServer } from "@/lib/mcp-proxy";
import { auditResponseRows, sumCostRows } from "@/lib/cost-rows";
import { COST_WARNING_TOPIC } from "./notification-topics";
import { publishHookNotification } from "./publish-notification";

const LAST_WARNED_AT_BY_DAY = new Map<string, number>();

export const costWarnOverBudgetBuiltin: BuiltinHookSpec = {
  name: "cost-warn-over-budget",
  displayName: "Cost warn over budget",
  description:
    "Fires a notification when the cumulative daily chat-turn cost " +
    "(across all sessions) crosses a threshold. Reads existing " +
    "chat_turn_cost audit rows; no schema change needed.",
  icon: "monetization_on",
  compatibleEvents: ["RunEnd"] as const,
  configFields: [
    {
      key: "threshold_usd",
      label: "Daily cost threshold (USD)",
      type: "number",
      min: 0,
      defaultValue: 10,
      helper:
        "Fire when cumulative cost since UTC midnight exceeds this. " +
        "Set to 0 to warn on the first turn of each repeat window " +
        "regardless of cost (the next one comes after the suppress " +
        "window below).",
      required: false,
    },
    {
      key: "suppress_repeat_hours",
      label: "Suppress repeat warnings within (hours)",
      type: "number",
      min: 0,
      max: 24,
      defaultValue: 1,
      helper:
        "Don't re-warn within this window even if the threshold is " +
        "still crossed. Prevents per-turn spam on a busy day. Set 0 " +
        "to warn on every turn over threshold.",
      required: false,
    },
  ] as const,
  validateConfig(raw) {
    if (raw && typeof raw !== "object") {
      return { ok: false, error: "config must be an object" };
    }
    const cfg = (raw ?? {}) as Record<string, unknown>;
    const out: Record<string, unknown> = {};

    const threshold = cfg.threshold_usd;
    if (threshold === undefined) out.threshold_usd = 10;
    else if (typeof threshold !== "number" || threshold < 0) {
      return { ok: false, error: "threshold_usd must be a non-negative number" };
    } else out.threshold_usd = threshold;

    const suppress = cfg.suppress_repeat_hours;
    if (suppress === undefined) out.suppress_repeat_hours = 1;
    else if (typeof suppress !== "number" || suppress < 0 || suppress > 24) {
      return { ok: false, error: "suppress_repeat_hours must be a number in [0, 24]" };
    } else out.suppress_repeat_hours = suppress;

    // `notify_category` is not read: the topic is fixed. Hooks saved before
    // that field was removed still carry it, so it is ignored here (and so
    // absent from the stored config the next time the hook is saved).

    return { ok: true, config: out };
  },
  async handle(_payload, config) {
    const threshold = config.threshold_usd as number;
    const suppressHrs = config.suppress_repeat_hours as number;

    // UTC-midnight day key. Suppression is per-day so a new day's
    // first crossing fires even if yesterday's already warned.
    const dayKey = new Date().toISOString().slice(0, 10);

    // Read today's chat_turn_cost audit rows. Best-effort — a failed
    // read shouldn't crash the chat loop.
    let totalUsd = 0;
    let unpricedCalls = 0;
    try {
      const sinceIso = `${dayKey}T00:00:00Z`;
      const resp = await callMcpServer<unknown>(
        `/api/v1/audit?action=chat_turn_cost&since=${encodeURIComponent(sinceIso)}&limit=10000`,
        { method: "GET" },
      );
      const totals = sumCostRows(auditResponseRows(resp));
      totalUsd = totals.usd;
      unpricedCalls = totals.unpricedCalls;
    } catch (err) {
      console.warn(
        "cost-warn-over-budget: failed to read audit log:",
        err instanceof Error ? err.message : err,
      );
      return null;
    }

    // Not over yet → no-op.
    if (threshold > 0 && totalUsd <= threshold) return null;

    // Suppression check.
    const nowMs = Date.now();
    const lastWarn = LAST_WARNED_AT_BY_DAY.get(dayKey);
    if (lastWarn !== undefined && suppressHrs > 0 && nowMs - lastWarn < suppressHrs * 3_600_000) {
      return null;
    }

    // Fire notification (best-effort; a failure is logged, never thrown).
    const published = await publishHookNotification("cost-warn-over-budget", COST_WARNING_TOPIC, {
      severity: "warn",
      title: `Daily chat cost crossed threshold — $${totalUsd.toFixed(2)} so far`,
      body:
        `Cumulative chat_turn_cost since UTC ${dayKey}T00:00:00Z is ` +
        `$${totalUsd.toFixed(2)}, above your threshold of ` +
        `$${threshold.toFixed(2)}. Open /observability/cost for the ` +
        `per-provider and per-model breakdown. ` +
        (unpricedCalls > 0
          ? `${unpricedCalls} call${unpricedCalls === 1 ? "" : "s"} to models with no known price are not in this total. `
          : "") +
        `Suppressed for ${suppressHrs}h after this.`,
      day: dayKey,
      total_usd: totalUsd,
      threshold_usd: threshold,
      unpriced_calls: unpricedCalls,
    });
    if (published) LAST_WARNED_AT_BY_DAY.set(dayKey, nowMs);
    return null; // non-decisional
  },
};
