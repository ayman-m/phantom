/**
 * Connector action proxy.
 *
 *   POST /api/agent/connectors/{id}/disable | enable | probe
 *
 * The {action} segment passes through verbatim; only the three
 * supported MCP-side actions are actually wired (other paths
 * just return whatever the MCP returns, typically 404).
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

const ALLOWED_ACTIONS = new Set(["disable", "enable", "probe"]);

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

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string; action: string }> },
) {
  const { id, action } = await params;
  if (!ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json(
      { error: `unknown action '${action}'` },
      { status: 400 },
    );
  }
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const upstream = await fetch(
      `${r.base}/api/v1/connectors/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${r.token}`,
          "Content-Type": "application/json",
        },
        body: "{}",
        signal: AbortSignal.timeout(10000),
      },
    );
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
