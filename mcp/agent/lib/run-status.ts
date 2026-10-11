/**
 * RunStatusReason
 *
 * Adapted from SnowAgent's terminal/continue reasons (snow-agent-
 * complete/snow-agent/04-query-engine/) — every chat turn has an
 * answer to "why did this stop or pause." Surfacing the reason on
 * the SSE done event AND the persisted assistant message gives
 * operators diagnostics they didn't have before.
 *
 * Today's chat-route ends turns silently in many cases:
 *   - max_output_tokens hit → assistant cuts off mid-sentence
 *   - max_turns hit → tool loop exits without explanation
 *   - hook denied → run aborts with an error event
 *   - context overflow → caught at provider, surfaces as a generic
 *     error
 *
 * With RunStatusReason set on every done event, the chat UI can
 * surface a small footer chip ("stopped: max_output_tokens") and
 * /observability/events queries can group session-ends by reason
 * to find systematic issues.
 */

/** All known reasons a chat turn ends. Closed list — add new ones
 *  here AND in the reason → label/severity helpers below. */
export type RunStatusReason =
  /** Normal completion — the model emitted a final text response. */
  | "completed"
  /** Operator interrupted via abort signal (browser navigation /
   *  reset). */
  | "aborted_by_operator"
  /** A PreToolUse / UserPromptSubmit / RunStart hook returned
   *  `decision: 'deny'`. Hook reason is in the run's metadata. */
  | "hook_denied"
  /** Model returned an error response (provider-side error, not
   *  a transport timeout). */
  | "model_error"
  /** Model emitted a too-long response and got truncated by the
   *  provider's max_output_tokens. The chat-route then composes a
   *  fallback narration; this reason flags that fallback fired. */
  | "max_output_truncation"
  /** The chat-route's tool-loop step counter hit its cap (default
   *  20) without the model producing a final text response. */
  | "max_turns_exceeded"
  /** Context-window guard — input + reserved-output
   *  tokens crossed the model's context cap and the chat-route
   *  bailed before sending. */
  | "context_overflow"
  /** A tool call's transport / approval / hook chain errored and
   *  no fallback worked. */
  | "tool_unrecoverable_error"
  /** The chat stream was disconnected (operator closed tab,
   *  network drop). */
  | "stream_disconnected"
  /** Slash command turn that doesn't fit any other category. The
   *  done event from /help / /clear / /tasks / etc. */
  | "slash_command_completed"
  /** /compress turn — distinct from generic slash completion so
   *  observability filters can split on this. */
  | "compaction_completed"
  /** /plan turn — no execution happened; just plan generation. */
  | "plan_proposed";

/** Operator-friendly label for a reason. */
export function statusReasonLabel(r: RunStatusReason): string {
  return {
    completed: "Completed",
    aborted_by_operator: "Aborted by operator",
    hook_denied: "Blocked by hook",
    model_error: "Model error",
    max_output_truncation: "Output truncated",
    max_turns_exceeded: "Max turns exceeded",
    context_overflow: "Context overflow",
    tool_unrecoverable_error: "Tool error",
    stream_disconnected: "Stream disconnected",
    slash_command_completed: "Slash command",
    compaction_completed: "Compaction",
    plan_proposed: "Plan proposed",
  }[r];
}

/** Severity tier — UI uses this to pick chip color. */
export function statusReasonTone(r: RunStatusReason): "ok" | "warn" | "err" | "neutral" {
  if (r === "completed") return "ok";
  if (r === "compaction_completed" || r === "plan_proposed") return "ok";
  if (r === "slash_command_completed") return "neutral";
  if (
    r === "aborted_by_operator" ||
    r === "max_output_truncation" ||
    r === "max_turns_exceeded" ||
    r === "stream_disconnected"
  ) {
    return "warn";
  }
  return "err";
}
