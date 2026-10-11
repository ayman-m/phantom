/**
 * Plugins reload proxy.
 *
 *   POST /api/agent/plugins/reload → re-apply enabled plugins
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

async function _resolveMcp(): Promise<
  { base: string; token: string } | NextResponse
> {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || "").trim() || process.env.MCP_TOKEN?.trim() || "";
  if (!mcpToken)
    return NextResponse.json(
      { error: "MCP_TOKEN not configured" },
      { status: 503 },
    );
  const mcpUrl =
    (config.MCP_URL || "").trim() ||
    process.env.MCP_URL?.trim() ||
    "http://phantom-mcp:8080/api/v1/stream/mcp";
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base)
    return NextResponse.json({ error: "bad MCP URL" }, { status: 500 });
  return { base, token: mcpToken };
}

export async function POST() {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const upstream = await fetch(`${r.base}/api/v1/plugins/reload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${r.token}`,
        "Content-Type": "application/json",
      },
      body: "{}",
      signal: AbortSignal.timeout(20000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: `MCP unreachable: ${err instanceof Error ? err.message : err}`,
      },
      { status: 502 },
    );
  }
}
