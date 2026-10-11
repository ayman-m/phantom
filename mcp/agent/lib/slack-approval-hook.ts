/**
 * Slack approval transport
 *
 * Helper for setting up a Slack-routed approval flow as a
 * hook, NOT a separate code path in the chat route.
 *
 * The hook framework already supports HTTP-transport
 * hooks that can return `decision: 'deny' | 'ask' | 'allow'`. A
 * Slack approval is just an HTTP hook that, on PreToolUse:
 *   1. POSTs the tool details to a Slack incoming webhook with
 *      Approve/Deny interactive buttons.
 *   2. Polls a callback URL until the SOC analyst clicks one.
 *   3. Returns the analyst's decision.
 *
 * This file ships a JSON snippet operators can paste into
 * /settings/hooks (or the MCP API) to install the hook. The actual
 * Slack-side implementation (the webhook receiver that records
 * approvals) lives in the operator's environment — it's a small
 * Lambda / Cloud Function / Slack-bot that:
 *   - receives the PreToolUse payload from the hook
 *   - posts to Slack with interactive buttons
 *   - records the analyst's click in a key/value store
 *   - serves a polling endpoint the hook can hit
 *
 * Why this isn't a built-in Slack code path: every customer's
 * Slack setup is different (workspace / channel / bot token /
 * approval-roster policy). Generic Slack approval would force
 * operators to fit our shape. The hook framework lets them bring
 * their own.
 *
 * Reference implementation skeleton (Pseudo):
 *
 *   // slack-approval-receiver.ts (operator's deploy)
 *   POST /pre-tool-approval-poll
 *     body: { event: 'PreToolUse', sessionId, toolName, args, ... }
 *     1. message_ts = slack.chat.postMessage({
 *          channel: '#soc-ops',
 *          blocks: [
 *            section: `Pre-tool approval needed: \`${toolName}\` ...`,
 *            actions: [
 *              { text: 'Approve', value: 'allow' },
 *              { text: 'Deny',    value: 'deny'  },
 *            ],
 *          ],
 *        });
 *     2. wait until store.get(message_ts) is set (Slack
 *        action handler writes it on click);
 *     3. return { decision: 'allow' | 'deny', reason: '...' }.
 *
 * The JSON snippet below registers an HTTP hook for `PreToolUse`
 * matching destructive tools, with a 60s timeout (Slack
 * round-trips can take a while if the analyst is offline).
 */

export interface SlackApprovalHookConfig {
  /** Operator-friendly name shown in /settings/hooks. */
  name: string;
  /** Where the operator's slack-approval-receiver listens. */
  webhookUrl: string;
  /** Optional auth header name+value the receiver expects. */
  authHeader?: { name: string; value: string };
  /** Tool glob — defaults to "caldera_*,xsiam_write_*,*_delete"
   *  (destructive families). Operator can override per-deployment. */
  toolGlob?: string;
  /** Failure policy. Default 'allow' (a slack-receiver outage
   *  shouldn't block all chat tool calls). Operator can override
   *  to 'block' for stricter SOC postures. */
  failurePolicy?: "block" | "allow" | "warn";
  /** Timeout in ms. Default 60000 — Slack round-trips with offline
   *  analysts can take real time. */
  timeoutMs?: number;
}

/** Build the Hook payload that registers a Slack approval hook.
 *  Operators can POST this to /api/agent/hooks (or paste into
 *  /settings/hooks add-form) to install the hook. */
export function buildSlackApprovalHookPayload(
  config: SlackApprovalHookConfig,
): {
  name: string;
  description: string;
  event: "PreToolUse";
  matcher: { toolGlob: string };
  transport: {
    type: "http";
    url: string;
    headers?: Record<string, string>;
  };
  timeoutMs: number;
  failurePolicy: "block" | "allow" | "warn";
  enabled: boolean;
  priority: number;
} {
  const headers: Record<string, string> | undefined = config.authHeader
    ? { [config.authHeader.name]: config.authHeader.value }
    : undefined;
  return {
    name: config.name,
    description:
      "Routes destructive-tool approvals through Slack. POSTs to " +
      "an operator-managed webhook receiver that pings #soc-ops " +
      "and waits for an analyst click.",
    event: "PreToolUse",
    matcher: {
      toolGlob:
        config.toolGlob ??
        "caldera_*,xsiam_write_*,*_delete,api_keys_*",
    },
    transport: {
      type: "http",
      url: config.webhookUrl,
      headers,
    },
    timeoutMs: config.timeoutMs ?? 60000,
    failurePolicy: config.failurePolicy ?? "allow",
    enabled: true,
    // Run BEFORE other PreToolUse hooks. If Slack denies, we
    // short-circuit any other policy hooks the operator has
    // installed.
    priority: 10,
  };
}

/** Operator-facing instructions text rendered in the
 *  `/settings/hooks` "Add new hook" panel as a help link. Kept here
 *  so the docs and the helper stay in sync. */
export const SLACK_APPROVAL_INSTRUCTIONS = `# Setting up Slack approval routing

The Phantom hook framework supports HTTP-transport hooks
that can deny/ask/allow tool calls. A Slack approval is just an HTTP
hook to a webhook receiver you deploy.

## What you need

1. **A small webhook receiver.** Lambda / Cloud Function / Cloud Run
   service / Slack bot — anything that:
   - Accepts POST with the PreToolUse JSON payload
   - Posts to Slack with Approve/Deny interactive buttons
   - Waits for the analyst's click
   - Returns \`{decision: "allow" | "deny", reason: "..."}\` as JSON

2. **A Slack incoming webhook URL or a Slack bot token** (your
   receiver decides).

3. **A list of which tools should route through Slack.** Default
   matches \`caldera_*\`, \`xsiam_write_*\`, \`*_delete\`, and
   \`api_keys_*\` — change to taste.

## Installing the hook

POST to \`/api/agent/hooks\` (or use the form in /settings/hooks):

\`\`\`json
{
  "name": "soc-ops slack approval",
  "event": "PreToolUse",
  "matcher": { "toolGlob": "caldera_*,xsiam_write_*,*_delete" },
  "transport": {
    "type": "http",
    "url": "https://your-receiver.example.com/pre-tool-approval-poll",
    "headers": { "X-Phantom-Auth": "secret:SLACK_APPROVAL_TOKEN" }
  },
  "timeoutMs": 60000,
  "failurePolicy": "allow",
  "priority": 10,
  "enabled": true
}
\`\`\`

## Behavior

- For every PreToolUse matching the toolGlob, the chat-route POSTs
  the payload to your URL and waits up to 60s.
- Your receiver pings Slack, waits for a click, returns the
  decision.
- \`decision: "deny"\` aborts the tool call with the analyst's reason.
- \`decision: "ask"\` triggers Phantom's standard inline approval
  card AS A FALLBACK (in case the Slack analyst defers to the
  in-chat operator).
- \`decision: "allow"\` lets the call proceed without the standard
  per-tool approval card. Use sparingly — bypasses self-modification gating.

## Failure policy

- \`failurePolicy: "allow"\` (default) — if your receiver errors or
  times out, the tool call proceeds. Best for "soft" Slack approval
  where SOC visibility is the goal but availability matters.
- \`failurePolicy: "block"\` — receiver outage = denied call. Best
  for strict SOC posture where any tool call without Slack
  visibility is a violation.

## Audit

Every dispatch lands in /observability/events as
\`action:hook_dispatched\` with metadata.per_hook[].decision.
Filter by your hook's name to audit Slack approval history.
`;
