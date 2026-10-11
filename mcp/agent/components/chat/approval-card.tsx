"use client";

/**
 * ApprovalCard — inline approval prompt rendered in the chat thread
 * when the agent calls a gated MCP tool (self-modification gating).
 *
 * The card adapts to the approval row's risk_tier:
 *
 *   "soft"        — Tier 2 writes (jobs_create, personality_update,
 *                   settings_update, etc). Green Approve button +
 *                   Deny. The default look.
 *
 *   "destructive" — Tier 3 (jobs_delete, instances_delete, …). Red
 *                   banner above the card with "this is irrecoverable"
 *                   text. Same buttons but the card border + icon are
 *                   error-colored.
 *
 *   "credential"  — Tier 4 (api_keys_*). Adds a "type CONFIRM" input
 *                   that gates the Approve button. Borrowed from
 *                   kubectl-delete + terraform-destroy: the friction
 *                   is the feature.
 *
 * For personality_update / settings_update the card fetches current
 * state and renders a compact diff so the operator sees what's
 * changing before approving.
 */

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import type { ApprovalRequest } from "@/lib/stores/chat";

export interface ApprovalCardProps {
  approval: ApprovalRequest;
  onResolve: (
    approvalId: string,
    resolution: "approved" | "denied",
    reason?: string,
  ) => void;
  className?: string;
}

function formatArguments(args: Record<string, unknown>): string {
  return JSON.stringify(args, null, 2);
}

/**
 * Inline key-args summary.
 *
 * Render a short list of the most-meaningful args directly above the
 * Approve/Deny buttons so the operator never has to expand "Raw
 * arguments" just to see what's happening. Same intent as the
 * server-side preamble synthesis in chat/route.ts but defense-in-depth
 * at the UI layer — even if the preamble somehow doesn't render
 * (rare race, custom-built client, etc.), the card itself is still
 * informative.
 *
 * Mirrors the chat/route.ts:formatToolPreamble logic for consistency:
 *   - Up to 4 keys; prefer human-meaningful ones first
 *   - Hide secret-looking keys (api_key, password, …)
 *   - Truncate any single value to 80 chars
 *
 * Returns an empty array when there's nothing useful to show; the
 * caller skips rendering the summary in that case.
 */
const PREFERRED_KEYS = [
  "name", "task", "goal", "prompt", "description", "cron",
  "connector_id", "instance_id", "instance_name",
  "url", "query", "pattern", "format", "destination",
  "scenario", "rate_per_second", "duration_seconds",
  "session_id", "tool_name", "reason",
];
const SECRET_KEY_RE = /^(api_?key|password|secret|token|bearer|kek|jwt)$/i;

function summarizeArgValue(v: unknown): string {
  if (v === null || v === undefined) return "∅";
  if (typeof v === "string") {
    const t = v.trim();
    return t.length > 80 ? `${t.slice(0, 77)}…` : t;
  }
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) {
    return `[${v.length === 0 ? "" : `${v.length} item${v.length === 1 ? "" : "s"}`}]`;
  }
  if (typeof v === "object") {
    const ks = Object.keys(v as Record<string, unknown>);
    return ks.length === 0 ? "{}" : `{${ks.slice(0, 3).join(", ")}${ks.length > 3 ? ", …" : ""}}`;
  }
  return String(v).slice(0, 80);
}

interface ArgSummaryEntry {
  key: string;
  value: string;
}

function buildArgSummary(args: Record<string, unknown> | undefined): {
  entries: ArgSummaryEntry[];
  hidden: number;
} {
  if (!args) return { entries: [], hidden: 0 };
  const allKeys = Object.keys(args);
  if (allKeys.length === 0) return { entries: [], hidden: 0 };
  const safeKeys = allKeys.filter((k) => !SECRET_KEY_RE.test(k));
  const preferred = PREFERRED_KEYS.filter((k) => safeKeys.includes(k));
  const remaining = safeKeys.filter((k) => !preferred.includes(k)).sort();
  const surface = [...preferred, ...remaining].slice(0, 4);
  const entries = surface.map((k) => ({ key: k, value: summarizeArgValue(args[k]) }));
  const hidden = safeKeys.length - surface.length;
  return { entries, hidden };
}

// Tier-keyed color tokens. Soft uses tertiary (orange-ish), destructive
// uses error, credential uses error with the extra ceremony.
function tierStyles(tier: ApprovalRequest["riskTier"]) {
  if (tier === "destructive" || tier === "credential") {
    return {
      borderColor: "border-error",
      iconBg: "bg-error/10",
      iconColor: "text-error",
      headlineColor: "text-error",
      icon: tier === "credential" ? "key" : "warning",
      banner: tier === "destructive"
        ? "Destructive — this cannot be undone."
        : "Credential operation — type CONFIRM to proceed.",
    };
  }
  // soft (default)
  return {
    borderColor: "border-tertiary",
    iconBg: "bg-tertiary/10",
    iconColor: "text-tertiary",
    headlineColor: "text-tertiary",
    icon: "shield",
    banner: null,
  };
}

interface DiffEntry {
  key: string;
  before: unknown;
  after: unknown;
}

/**
 * For personality_update + settings_update, fetch the current state
 * and compute a diff against the proposed args. Returns null while
 * loading or when the tool doesn't have a diff representation.
 */
function useDiff(approval: ApprovalRequest): {
  loading: boolean;
  entries: DiffEntry[] | null;
  error: string | null;
} {
  const [state, setState] = useState<{
    loading: boolean;
    entries: DiffEntry[] | null;
    error: string | null;
  }>({ loading: false, entries: null, error: null });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const args = approval.arguments ?? {};
      try {
        if (approval.tool === "personality_update") {
          // Fetch current personality, diff its keys against the
          // ones the agent proposes (sent as `blob_keys`). We don't
          // have the proposed VALUES (the chat-route sends keys-only
          // to keep the approval row small), so the diff lists what
          // keys are about to change without showing the new values.
          // The operator sees "responseStyle, personalityMd" as a
          // change list; full inspection happens in the personality
          // page after approval.
          setState({ loading: true, entries: null, error: null });
          const r = await fetch("/api/agent/personality", { cache: "no-store" });
          if (!r.ok) throw new Error(`personality fetch ${r.status}`);
          const cur = (await r.json()) as { personality?: Record<string, unknown> };
          const blobKeys = Array.isArray(args.blob_keys)
            ? (args.blob_keys as string[])
            : [];
          const entries: DiffEntry[] = blobKeys.map((k) => ({
            key: k,
            before: (cur.personality ?? {})[k],
            after: "(agent-proposed value)",
          }));
          if (!cancelled) setState({ loading: false, entries, error: null });
          return;
        }
        if (approval.tool === "settings_update") {
          setState({ loading: true, entries: null, error: null });
          const r = await fetch("/api/agent/settings", { cache: "no-store" });
          if (!r.ok) throw new Error(`settings fetch ${r.status}`);
          const cur = (await r.json()) as { effective?: Record<string, unknown> };
          const updateKeys = Array.isArray(args.update_keys)
            ? (args.update_keys as string[])
            : [];
          const clearKeys = Array.isArray(args.clear) ? (args.clear as string[]) : [];
          const entries: DiffEntry[] = [
            ...updateKeys.map((k) => ({
              key: k,
              before: (cur.effective ?? {})[k],
              after: "(agent-proposed value)",
            })),
            ...clearKeys.map((k) => ({
              key: k,
              before: (cur.effective ?? {})[k],
              after: "(reset to default)",
            })),
          ];
          if (!cancelled) setState({ loading: false, entries, error: null });
          return;
        }
        // Other tools: no diff representation. Return null.
        setState({ loading: false, entries: null, error: null });
      } catch (err) {
        if (cancelled) return;
        setState({
          loading: false,
          entries: null,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // approval.id is the cache key — diff stays stable for one row.
  }, [approval.id, approval.tool, approval.arguments]);

  return state;
}

export function ApprovalCard({
  approval,
  onResolve,
  className,
}: ApprovalCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [confirmInput, setConfirmInput] = useState("");

  const isPending = approval.status === "pending";
  const tier = approval.riskTier ?? "soft";
  const styles = tierStyles(tier);
  const hasArguments =
    approval.arguments != null &&
    Object.keys(approval.arguments).length > 0;
  const argSummary = buildArgSummary(approval.arguments);

  // agent_batch_propose detection. The MCP-side batch tool
  // stores its plan in args.actions = [{tool, args}, ...] plus a
  // pre-computed args.summary string. The card uses these to render
  // the per-action list instead of the standard single-action summary.
  const batchData = (() => {
    if (approval.tool !== "agent_batch_propose") return null;
    const args = approval.arguments as Record<string, unknown> | undefined;
    if (!args) return null;
    const raw = args["actions"];
    if (!Array.isArray(raw)) return null;
    const actions = raw.map((item) => {
      const o = (item ?? {}) as Record<string, unknown>;
      const tool = typeof o["tool"] === "string" ? (o["tool"] as string) : "?";
      const innerArgs = (o["args"] ?? {}) as Record<string, unknown>;
      // Compose a one-line preview of the args so the operator can
      // tell apart two same-tool actions in the list (e.g. two
      // jobs_create calls with different `name`s).
      const sum = buildArgSummary(innerArgs);
      const summary = sum.entries
        .slice(0, 2)
        .map((e) => `${e.key}=${e.value}`)
        .join("  ");
      return { tool, summary };
    });
    const overall = typeof args["summary"] === "string"
      ? (args["summary"] as string)
      : null;
    return { actions, summary: overall };
  })();
  const isBatchRequest = batchData != null;
  const batchActions = batchData?.actions ?? [];
  const batchSummary = batchData?.summary ?? null;

  // Credential tier requires the literal "CONFIRM" string typed into
  // the input before the Approve button activates. Same friction model
  // as `kubectl delete --grace-period=0 --force` confirmations.
  const confirmRequired = tier === "credential";
  const canApprove = !confirmRequired || confirmInput.trim() === "CONFIRM";

  const diff = useDiff(approval);

  function handleResolve(resolution: "approved" | "denied") {
    if (resolution === "approved" && !canApprove) return;
    setIsResolving(true);
    onResolve(approval.id, resolution);
  }

  return (
    <div
      className={cn(
        // Iteration 2 of the size reduction. Goal: about the size of a
        // chat bubble (max-w-sm, p-3) with a single-line header
        // ("Approve: <tool>") and a compact button row. Watermark
        // gone — at this size it was just visual noise. Tier banners
        // and the diff/raw-args sections still expand the card when
        // present (destructive ops genuinely need the explanation).
        "max-w-sm bg-surface-container-high rounded-lg p-3 border-l-[3px] shadow-md overflow-hidden",
        isPending
          ? styles.borderColor
          : approval.status === "approved"
            ? "border-secondary"
            : "border-error",
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <div
          className={cn(
            "w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5",
            styles.iconBg,
            styles.iconColor,
          )}
        >
          <span className="material-symbols-outlined text-[16px]">
            {styles.icon}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          {/* Title + tool collapsed onto one line. The full
              `approval.tool` is in the title attribute for hover. */}
          <h4
            className={cn(
              "font-headline font-bold text-xs leading-tight mb-1 truncate",
              styles.headlineColor,
            )}
            title={approval.tool}
          >
            {tier === "credential"
              ? "Credential approval"
              : tier === "destructive"
                ? "Destructive action"
                : "Approval required"}
            <span className="ml-1.5 font-mono text-[10px] opacity-70">
              · {approval.tool}
            </span>
          </h4>

          {styles.banner && isPending && (
            <div
              className={cn(
                "rounded-md px-2 py-1.5 mb-2 text-[11px] leading-snug font-medium",
                tier === "destructive"
                  ? "bg-error/10 text-error border border-error/30"
                  : "bg-error/5 text-error/80 border border-error/20",
              )}
            >
              <span className="material-symbols-outlined text-[13px] align-middle mr-1">
                {tier === "credential" ? "key" : "delete_forever"}
              </span>
              {styles.banner}
            </div>
          )}

          {/* agent_batch_propose renders the action list
              instead of the standard arg summary. Each action shows
              the tool name + a short args preview so the operator
              sees the whole plan before approving. */}
          {isBatchRequest && (
            <div className="mb-3">
              <div className="text-[9px] font-headline uppercase tracking-widest text-on-surface-variant mb-1">
                Proposed batch ({batchActions.length}{" "}
                {batchActions.length === 1 ? "action" : "actions"})
              </div>
              <div className="rounded-md bg-surface-container-lowest/50 divide-y divide-on-surface/5 max-h-64 overflow-y-auto">
                {batchActions.map((act, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2 px-2 py-1.5 text-[11px]"
                  >
                    <span className="font-mono text-[10px] text-on-surface-variant/60 w-5 shrink-0 mt-0.5">
                      {idx + 1}.
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="font-mono font-semibold text-primary truncate">
                        {act.tool}
                      </div>
                      {act.summary && (
                        <div
                          className="font-mono text-[10px] text-on-surface-variant/80 truncate"
                          title={act.summary}
                        >
                          {act.summary}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              {batchSummary && (
                <div className="mt-1 text-[10px] text-on-surface-variant/60 italic">
                  {batchSummary}
                </div>
              )}
            </div>
          )}

          {/* Inline key-args summary. Always-visible
              one-liner of the most-meaningful args so the operator
              never has to hit the "Raw arguments" expander to
              understand what's being approved. The full args (and
              any args we suppressed for being secret-looking) live
              in the expander below. */}
          {!isBatchRequest && argSummary.entries.length > 0 && !diff.entries && (
            <div className="mb-3 rounded-md bg-surface-container-lowest/40 px-2.5 py-1.5">
              <div className="text-[9px] font-headline uppercase tracking-widest text-on-surface-variant/80 mb-1">
                Will be called with
              </div>
              <div className="space-y-0.5 text-[11px] font-mono">
                {argSummary.entries.map((e) => (
                  <div key={e.key} className="flex gap-2">
                    <span className="text-primary font-semibold shrink-0">
                      {e.key}
                    </span>
                    <span
                      className="text-on-surface-variant truncate flex-1 min-w-0"
                      title={e.value}
                    >
                      {e.value}
                    </span>
                  </div>
                ))}
                {argSummary.hidden > 0 && (
                  <div className="text-[10px] text-on-surface-variant/60 pt-0.5">
                    + {argSummary.hidden} more in raw arguments
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Diff renderer (personality_update / settings_update) */}
          {diff.entries && diff.entries.length > 0 && (
            <div className="mb-3">
              <div className="text-[9px] font-headline uppercase tracking-widest text-on-surface-variant mb-1">
                Proposed changes
              </div>
              <div className="rounded-md bg-surface-container-lowest/50 divide-y divide-on-surface/5">
                {diff.entries.map((entry) => (
                  <div
                    key={entry.key}
                    className="flex items-start gap-2 px-2 py-1.5 text-[11px] font-mono"
                  >
                    <span className="text-primary font-semibold shrink-0">
                      {entry.key}
                    </span>
                    <div className="flex-1 min-w-0 grid grid-cols-2 gap-2">
                      <div>
                        <div className="text-[9px] uppercase tracking-wider text-on-surface-variant/60">
                          before
                        </div>
                        <div className="truncate text-error/80" title={String(entry.before ?? "")}>
                          {String(entry.before ?? "(unset)")}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] uppercase tracking-wider text-on-surface-variant/60">
                          after
                        </div>
                        <div className="truncate text-secondary/80" title={String(entry.after ?? "")}>
                          {String(entry.after ?? "(unset)")}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {diff.loading && (
            <div className="mb-2 text-[11px] text-on-surface-variant/60">
              Loading diff…
            </div>
          )}

          {/* Raw arguments (collapsible) — collapsed by default keeps
              the card short; the operator opens it only when the
              tool name + diff aren't enough context. */}
          {hasArguments && (
            <div className="mb-3">
              <button
                type="button"
                aria-expanded={isExpanded}
                onClick={() => setIsExpanded((current) => !current)}
                className="flex items-center gap-1 text-[9px] font-headline uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors mb-1"
              >
                <span
                  className={cn(
                    "material-symbols-outlined text-[13px] transition-transform",
                    isExpanded && "rotate-180",
                  )}
                  aria-hidden="true"
                >
                  expand_more
                </span>
                Raw arguments
              </button>
              {isExpanded && (
                <pre className="max-h-40 overflow-auto rounded-md bg-surface-container-lowest/50 p-2 text-[11px] font-mono text-on-surface-variant leading-relaxed">
                  {formatArguments(approval.arguments!)}
                </pre>
              )}
            </div>
          )}

          {/* Credential confirm input */}
          {isPending && confirmRequired && (
            <div className="mb-2">
              <label className="text-[9px] font-headline uppercase tracking-widest text-on-surface-variant mb-1 block">
                Type <code className="font-mono text-error">CONFIRM</code> to enable Approve
              </label>
              <input
                type="text"
                value={confirmInput}
                onChange={(e) => setConfirmInput(e.target.value)}
                placeholder="CONFIRM"
                className={cn(
                  "w-full px-2.5 py-1.5 text-xs font-mono bg-surface-container-lowest/50 rounded-md",
                  "border border-error/30 focus:border-error outline-none",
                  "placeholder:text-on-surface-variant/30",
                )}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          )}

          {isPending ? (
            <div className="flex gap-1.5">
              <button
                type="button"
                disabled={isResolving || !canApprove}
                onClick={() => handleResolve("approved")}
                className={cn(
                  "flex-1 font-headline font-bold py-1 rounded text-[10px] uppercase tracking-widest active:scale-95 duration-150 disabled:opacity-50",
                  tier === "soft"
                    ? "bg-secondary text-on-secondary"
                    : "bg-error text-on-error",
                )}
              >
                {confirmRequired && !canApprove ? "Type CONFIRM" : "Approve"}
              </button>
              <button
                type="button"
                disabled={isResolving}
                onClick={() => handleResolve("denied")}
                className="flex-1 border border-on-surface-variant/30 text-on-surface-variant font-headline font-bold py-1 rounded text-[10px] uppercase tracking-widest hover:bg-on-surface/5 active:scale-95 duration-150 disabled:opacity-50"
              >
                Deny
              </button>
            </div>
          ) : (
            <p
              className={cn(
                "text-[10px] font-bold uppercase tracking-widest",
                approval.status === "approved" ? "text-secondary" : "text-error",
              )}
            >
              {approval.status === "approved" ? "✓ Approved" : "✗ Denied"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
