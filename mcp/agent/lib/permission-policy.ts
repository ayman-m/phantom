/**
 * Permission policy evaluator.
 *
 * The chat-route's tool-dispatch loop consults this module before each
 * tool call to decide whether the tool should fire, be denied, or
 * require operator approval. Policies are declarative, JSON-shaped
 * (operator-editable from /jobs/new), and stored per-job in jobs.db's
 * `permission_policy_json` column. The scheduler threads the stored
 * policy through `body.permission_policy` on the chat dispatch; the
 * chat-route destructures it + invokes `evaluatePermissionPolicy`
 * per tool call.
 *
 * Glob syntax mirrors `globMatch` in `lib/hooks.ts` — `*` matches any
 * sequence, `?` matches a single character, comma-separated lists are
 * OR. We re-implement here rather than importing to keep this module
 * decoupled (hooks.ts already imports from hook-builtins; circular
 * dependency surface area grows fast if we add another consumer).
 *
 * Evaluation precedence (narrowest match wins):
 *
 *   1. `denied_tools` match     → decision = "deny"
 *   2. `require_approval` match → decision = "ask"
 *   3. `allowed_tools` non-empty AND no match → decision = "deny"
 *      (i.e. allowed_tools is a WHITELIST when non-empty)
 *   4. Otherwise                → decision = "allow"
 *
 * Empty/missing policy = fully permissive (the operator opts INTO
 * restrictions): permissive by default, restrictive only when the
 * operator explicitly configures.
 *
 * NOT a security boundary by itself. The MCP-side approval gate
 * remains the authoritative defense for destructive tools (the
 * humanRequired list). Permission policies are an
 * operator-facing scope check — "don't even *try* this tool from this
 * job" — that runs BEFORE the approval gate. Defense in depth.
 */

/** Operator-facing shape stored verbatim in jobs.db. */
export interface PermissionPolicy {
  allowed_tools?: string[];
  denied_tools?: string[];
  require_approval?: string[];
}

/** Outcome of `evaluatePermissionPolicy`. The chat-route maps these
 *  to per-tool-call behavior:
 *   - `allow` → fire the tool as normal (other policy paths may still
 *     gate, e.g. the approval gate).
 *   - `deny`  → short-circuit; the model sees a synthetic error
 *     "Tool denied by job permission policy". The thread renders the
 *     denial reason as a tool-error response.
 *   - `ask`   → trigger the standard inline approval card. The
 *     scheduler's `bypass_approvals=true` flag does NOT override
 *     `ask` from the policy — operator must explicitly grant. */
export type PolicyDecision = "allow" | "deny" | "ask";

export interface PolicyEvaluation {
  decision: PolicyDecision;
  /** Operator-visible reason. Empty for `allow`; populated for `deny`
   *  + `ask` with a one-line "denied by `denied_tools` match
   *  `caldera_*`" style string the chat thread surfaces. */
  reason?: string;
  /** Which list matched. Useful for audit row metadata. */
  matchedList?: "allowed_tools" | "denied_tools" | "require_approval";
  /** The specific pattern that matched. Same purpose. */
  matchedPattern?: string;
}

/**
 * Evaluate a tool call against a policy. Pure function — no I/O.
 *
 * @param toolName Canonical MCP tool name (no namespace prefix).
 * @param policy The policy to apply, or undefined for "no policy"
 *   (always allow).
 */
export function evaluatePermissionPolicy(
  toolName: string,
  policy: PermissionPolicy | undefined | null,
): PolicyEvaluation {
  if (!policy || typeof policy !== "object") {
    return { decision: "allow" };
  }
  const denied = Array.isArray(policy.denied_tools) ? policy.denied_tools : [];
  const requireApproval = Array.isArray(policy.require_approval)
    ? policy.require_approval
    : [];
  const allowed = Array.isArray(policy.allowed_tools) ? policy.allowed_tools : [];

  // 1. Deny beats everything.
  for (const pattern of denied) {
    if (matchesGlobList(toolName, pattern)) {
      return {
        decision: "deny",
        reason: `Denied by policy.denied_tools pattern \`${pattern}\``,
        matchedList: "denied_tools",
        matchedPattern: pattern,
      };
    }
  }
  // 2. Require-approval routes through the standard approval card.
  for (const pattern of requireApproval) {
    if (matchesGlobList(toolName, pattern)) {
      return {
        decision: "ask",
        reason: `Approval required by policy.require_approval pattern \`${pattern}\``,
        matchedList: "require_approval",
        matchedPattern: pattern,
      };
    }
  }
  // 3. Allowed list is a whitelist when non-empty.
  if (allowed.length > 0) {
    for (const pattern of allowed) {
      if (matchesGlobList(toolName, pattern)) {
        return {
          decision: "allow",
          matchedList: "allowed_tools",
          matchedPattern: pattern,
        };
      }
    }
    return {
      decision: "deny",
      reason:
        "Denied — tool is not in policy.allowed_tools (whitelist mode)",
    };
  }
  // 4. No constraints → allow.
  return { decision: "allow" };
}

/**
 * Match `subject` against a comma-separated list of globs. Each item
 * is trimmed; empty items are ignored. Returns true on first match.
 */
export function matchesGlobList(subject: string, patternList: string): boolean {
  return patternList
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .some((p) => matchesGlobSingle(subject, p));
}

function matchesGlobSingle(subject: string, pattern: string): boolean {
  // Convert glob to anchored regex: escape regex chars, then `.*` for
  // `*`, `.` for `?`.
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(
    "^" + escaped.replace(/\*/g, ".*").replace(/\?/g, ".") + "$",
  );
  return re.test(subject);
}

/**
 * Lightweight runtime validator. Returns the policy in normalized form
 * (arrays defaulted, strings trimmed) or null when the shape is
 * obviously wrong. The chat-route uses this on the body-destructured
 * field; the agent-side /jobs UI also runs this before POST.
 */
export function validatePermissionPolicy(raw: unknown): PermissionPolicy | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const out: PermissionPolicy = {};
  for (const key of [
    "allowed_tools",
    "denied_tools",
    "require_approval",
  ] as const) {
    const v = r[key];
    if (v === undefined || v === null) continue;
    if (!Array.isArray(v)) return null;
    const cleaned: string[] = [];
    for (const item of v) {
      if (typeof item !== "string") return null;
      const trimmed = item.trim();
      if (trimmed) cleaned.push(trimmed);
    }
    if (cleaned.length > 0) out[key] = cleaned;
  }
  return out;
}
