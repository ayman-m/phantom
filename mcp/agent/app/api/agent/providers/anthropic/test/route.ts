/**
 * POST /api/agent/providers/anthropic/test
 *
 * The Providers page's Test Connection button for the Anthropic card.
 *
 * Body (JSON):  { api_key?: string | "***", base_url?: string }
 *
 *   api_key "***" (or empty) means "test the saved key"; it is resolved here,
 *           server-side, and only against the base URL it was saved with.
 *   base_url optional; empty means https://api.anthropic.com. It passes the
 *           outbound-URL guard (https only, no loopback, link-local or
 *           install-internal hosts, no redirects).
 *
 * The check is GET /v1/models, which costs no tokens.
 *
 * Response, always HTTP 200 like vertex/test:
 *   { status: "success" | "error", message, modelCount? }
 *
 * Each call writes an audit row `provider_test` with {provider, ok, status};
 * the key is never logged or returned. The route sits under
 * /api/agent/providers, so API keys are refused with 403 (the credential-route
 * guardrail in lib/agent-scopes.ts).
 */

import { NextResponse } from "next/server";

import { callMcpServer } from "@/lib/mcp-proxy";
import { mcpBlockedHosts } from "@/lib/mcp-host";
import { createAnthropicAdapter } from "@/lib/providers/anthropic/adapter";
import { runProviderConnectionTest } from "@/lib/providers/connection-test";
import { resolveProviderCreds } from "@/lib/providers/credentials";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ status: "error", message: "Request body must be valid JSON." });
  }
  const result = await runProviderConnectionTest("anthropic", body, {
    adapter: createAnthropicAdapter({ blockedHosts: mcpBlockedHosts() }),
    resolveCreds: (provider) => resolveProviderCreds(provider),
    audit: async (row) => {
      await callMcpServer("/api/v1/audit", {
        method: "POST",
        body: {
          action: "provider_test",
          target: `provider:${row.provider}`,
          status: row.ok ? "success" : "failure",
          metadata: { provider: row.provider, ok: row.ok, status: row.status },
        },
      });
    },
  });
  return NextResponse.json(result);
}
