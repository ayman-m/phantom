/**
 * Slack approval builtin.
 *
 * POSTs the `PreToolUse` payload to an operator-managed webhook
 * receiver that pings Slack with Approve/Deny buttons, waits for the
 * analyst's click, and returns their decision. The operator installs
 * it from `/settings/hooks` with a single dropdown pick + URL +
 * auth-header — no JSON pasting.
 *
 * `lib/slack-approval-hook.ts` is an alternative helper that produces
 * an equivalent `http`-transport hook for operators who prefer to
 * paste a hook payload by hand.
 */

import type { BuiltinHookSpec } from "./types";

export const slackApprovalBuiltin: BuiltinHookSpec = {
  name: "slack-approval",
  displayName: "Slack approval",
  description:
    "Routes destructive-tool approvals through Slack. POSTs the PreToolUse " +
    "payload to your webhook receiver that pings #soc-ops with " +
    "Approve/Deny buttons, then returns the analyst's decision.",
  icon: "chat",
  compatibleEvents: ["PreToolUse", "PermissionRequest"] as const,
  configFields: [
    {
      key: "webhookUrl",
      label: "Webhook URL",
      type: "url",
      placeholder: "https://your-receiver.example.com/pre-tool-approval-poll",
      helper:
        "Your slack-approval-receiver endpoint (Lambda / Cloud Run / Slack-bot). " +
        "POSTed with the PreToolUse payload; must respond with " +
        '`{"decision":"allow"|"deny","reason":"..."}`.',
      required: true,
    },
    {
      key: "authHeaderName",
      label: "Auth header name (optional)",
      type: "string",
      placeholder: "X-Phantom-Auth",
      helper:
        "If your receiver requires an auth header, name it here. " +
        "Leave blank for no auth header.",
    },
    {
      key: "authHeaderValue",
      label: "Auth header value (optional)",
      type: "secret-ref",
      placeholder: "secret:SLACK_APPROVAL_TOKEN",
      helper:
        "Header value. Use `secret:<ENV_NAME>` to read from the agent's " +
        "environment instead of storing the token in plaintext.",
    },
  ] as const,
  validateConfig(raw) {
    if (!raw || typeof raw !== "object") {
      return { ok: false, error: "config must be an object" };
    }
    const cfg = raw as Record<string, unknown>;
    const webhookUrl = cfg.webhookUrl;
    if (typeof webhookUrl !== "string" || !webhookUrl.trim()) {
      return { ok: false, error: "webhookUrl is required" };
    }
    try {
      const parsed = new URL(webhookUrl);
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
        return {
          ok: false,
          error: "webhookUrl must be http(s):// — Slack receivers expect HTTP",
        };
      }
    } catch {
      return { ok: false, error: `webhookUrl is not a valid URL: ${webhookUrl}` };
    }
    const authName = cfg.authHeaderName;
    if (authName !== undefined && typeof authName !== "string") {
      return { ok: false, error: "authHeaderName must be a string when set" };
    }
    const authValue = cfg.authHeaderValue;
    if (authValue !== undefined && typeof authValue !== "string") {
      return { ok: false, error: "authHeaderValue must be a string when set" };
    }
    // Both-or-neither — partial auth header is a misconfig.
    const hasName = typeof authName === "string" && authName.trim().length > 0;
    const hasValue = typeof authValue === "string" && authValue.trim().length > 0;
    if (hasName !== hasValue) {
      return {
        ok: false,
        error: "authHeaderName + authHeaderValue must be set together (or both blank)",
      };
    }
    return {
      ok: true,
      config: {
        webhookUrl,
        ...(hasName && hasValue
          ? { authHeaderName: authName, authHeaderValue: authValue }
          : {}),
      },
    };
  },
  async handle(payload, config, options) {
    const webhookUrl = config.webhookUrl as string;
    const authHeaderName = config.authHeaderName as string | undefined;
    const authHeaderValue = config.authHeaderValue as string | undefined;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (authHeaderName && authHeaderValue) {
      headers[authHeaderName] = resolveSecretRef(authHeaderValue);
    }
    const resp = await fetch(webhookUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: options.signal,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(
        `slack-approval receiver HTTP ${resp.status}: ${text.slice(0, 200)}`,
      );
    }
    const text = await resp.text();
    if (!text.trim()) return {};
    try {
      return JSON.parse(text) as Awaited<ReturnType<BuiltinHookSpec["handle"]>>;
    } catch (err) {
      throw new Error(
        `slack-approval receiver returned non-JSON body: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  },
};

/** Resolve a `secret:<envvar>` ref against process.env. Plain values pass
 *  through unchanged. Matches the same resolution pattern as
 *  `resolveSecretEnv` in `lib/hook-runner.ts`. */
function resolveSecretRef(value: string): string {
  if (!value.startsWith("secret:")) return value;
  const envKey = value.slice("secret:".length);
  return process.env[envKey] ?? "";
}
