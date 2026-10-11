/**
 * Tool-output evidence truncation.
 *
 * Long tool outputs (e.g. `xlog_logs_tail(count=1000)`) would blow the
 * agent's context window with 200K of repetitive log noise that
 * crowds out the actual reasoning context AND inflates input-token
 * cost on every subsequent turn until compaction. The chat route
 * therefore replaces the middle of a large output with a marker and
 * keeps the head + tail.
 *
 * Truncation strategy: when output exceeds `maxBytes`, take the
 * first `headKeep` bytes + the last `tailKeep` bytes + a marker
 * line in between announcing the truncation. The marker mentions
 * how many bytes were dropped + a hint that the agent can call a
 * follow-up slice tool to fetch a specific window if the operator
 * needs more.
 *
 * Structured returns (JSON / arrays) are NOT truncated by default
 * — slicing mid-JSON breaks the parser the agent uses. Operators
 * who specifically want to truncate structured returns can pass
 * `applyToStructured: true` (their problem if the agent gets
 * garbage).
 *
 * Configuration: the chat-route process reads these env vars (there
 * is no per-job or per-tool setting):
 *
 *   EVIDENCE_TRUNCATION_ENABLED  ("true" / "false", default "true")
 *   EVIDENCE_TRUNCATION_MAX_BYTES (integer, default 16384)
 *   EVIDENCE_TRUNCATION_HEAD_BYTES (integer, default 4096)
 *   EVIDENCE_TRUNCATION_TAIL_BYTES (integer, default 4096)
 */

export interface TruncationPolicy {
  enabled: boolean;
  maxBytes: number;
  headKeep: number;
  tailKeep: number;
  markerTemplate: string;
  applyToStructured: boolean;
}

export const DEFAULT_TRUNCATION_POLICY: Readonly<TruncationPolicy> = Object.freeze({
  enabled: true,
  maxBytes: 16_384,
  headKeep: 4_096,
  tailKeep: 4_096,
  markerTemplate:
    "\n[... truncated {N} bytes — ask the operator if you need a specific window ...]\n",
  applyToStructured: false,
});

/** Read env-var overrides on the default policy. Returns a frozen copy
 *  the caller can use. Reads happen at every call; the chat-route can
 *  toggle truncation without restart by changing the env. */
export function policyFromEnv(): TruncationPolicy {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env ?? {};
  const enabled =
    env.EVIDENCE_TRUNCATION_ENABLED === undefined
      ? DEFAULT_TRUNCATION_POLICY.enabled
      : env.EVIDENCE_TRUNCATION_ENABLED.toLowerCase() === "true";
  const parseInt = (raw: string | undefined, dflt: number): number => {
    if (!raw) return dflt;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : dflt;
  };
  return Object.freeze({
    enabled,
    maxBytes: parseInt(env.EVIDENCE_TRUNCATION_MAX_BYTES, DEFAULT_TRUNCATION_POLICY.maxBytes),
    headKeep: parseInt(env.EVIDENCE_TRUNCATION_HEAD_BYTES, DEFAULT_TRUNCATION_POLICY.headKeep),
    tailKeep: parseInt(env.EVIDENCE_TRUNCATION_TAIL_BYTES, DEFAULT_TRUNCATION_POLICY.tailKeep),
    markerTemplate: DEFAULT_TRUNCATION_POLICY.markerTemplate,
    applyToStructured: DEFAULT_TRUNCATION_POLICY.applyToStructured,
  });
}

export interface TruncationResult {
  /** The (possibly-truncated) output value the chat-route should feed
   *  back to the model. Same type as the input — string in, string
   *  out; structured in, structured out (untruncated by default). */
  output: unknown;
  /** True when truncation fired; false when the output passed through
   *  unchanged. */
  truncated: boolean;
  /** How many bytes were dropped (0 when not truncated). */
  bytesDropped: number;
  /** How many bytes the truncated output is (== original.length when
   *  not truncated). */
  bytesKept: number;
  /** When `truncated` is true, the head + tail sizes used. Useful for
   *  audit metadata. */
  headKept?: number;
  tailKept?: number;
}

/**
 * Apply truncation policy to a tool's result.
 *
 * Behavior:
 *   - Disabled or applied to a value that's already small → pass-
 *     through.
 *   - String output longer than `maxBytes` → head + marker + tail.
 *   - Structured output (object / array) is NOT truncated by default;
 *     operators who want it must set `policy.applyToStructured = true`
 *     (acknowledging the model may get unparseable JSON).
 *   - Null / undefined / boolean / number pass through unchanged.
 */
export function applyTruncation(
  toolName: string,
  output: unknown,
  policy: TruncationPolicy = DEFAULT_TRUNCATION_POLICY,
): TruncationResult {
  if (!policy.enabled) {
    return {
      output,
      truncated: false,
      bytesDropped: 0,
      bytesKept: byteLength(output),
    };
  }

  // String output — the common case. Truncate when length > maxBytes.
  if (typeof output === "string") {
    if (output.length <= policy.maxBytes) {
      return { output, truncated: false, bytesDropped: 0, bytesKept: output.length };
    }
    const head = output.slice(0, policy.headKeep);
    const tail = output.slice(output.length - policy.tailKeep);
    const dropped = output.length - head.length - tail.length;
    const marker = policy.markerTemplate.replace("{N}", String(dropped));
    return {
      output: head + marker + tail,
      truncated: true,
      bytesDropped: dropped,
      bytesKept: head.length + marker.length + tail.length,
      headKept: head.length,
      tailKept: tail.length,
    };
  }

  // Structured output. Default: pass-through (truncating mid-JSON
  // breaks parsing). Operators who explicitly opt-in get the same
  // string-truncation treatment applied to the JSON-stringified form
  // — they accept that the model may see unparseable JSON.
  if (policy.applyToStructured && output !== null && typeof output === "object") {
    const stringified = JSON.stringify(output);
    if (stringified.length <= policy.maxBytes) {
      return {
        output,
        truncated: false,
        bytesDropped: 0,
        bytesKept: stringified.length,
      };
    }
    const head = stringified.slice(0, policy.headKeep);
    const tail = stringified.slice(stringified.length - policy.tailKeep);
    const dropped = stringified.length - head.length - tail.length;
    const marker = policy.markerTemplate.replace("{N}", String(dropped));
    return {
      output: head + marker + tail, // string, no longer structured
      truncated: true,
      bytesDropped: dropped,
      bytesKept: head.length + marker.length + tail.length,
      headKept: head.length,
      tailKept: tail.length,
    };
  }

  // Everything else (null / boolean / number / structured-without-
  // opt-in) → pass-through.
  return {
    output,
    truncated: false,
    bytesDropped: 0,
    bytesKept: byteLength(output),
  };
}

function byteLength(v: unknown): number {
  if (typeof v === "string") return v.length;
  if (v === null || v === undefined) return 0;
  if (typeof v === "object") {
    try {
      return JSON.stringify(v).length;
    } catch {
      return 0;
    }
  }
  return String(v).length;
}
