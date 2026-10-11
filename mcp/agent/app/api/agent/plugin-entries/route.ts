/**
 * Plugin entry-points proxy.
 *
 * Distinct from /api/agent/plugins (which proxies to the
 * filesystem-plugin surface). This one proxies to the entry-point
 * discovery API (`/api/v1/plugin-entries`). Used by
 * /observability/plugins.
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

export async function GET() {
  const config = await getEffectiveRuntimeConfig();
  const token =
    (config.MCP_TOKEN || "").trim() || process.env.MCP_TOKEN?.trim() || "";
  if (!token)
    return NextResponse.json({ error: "MCP_TOKEN not configured" }, { status: 503 });
  const mcpUrl =
    (config.MCP_URL || "").trim() ||
    process.env.MCP_URL?.trim() ||
    "http://phantom-mcp:8080/api/v1/stream/mcp";
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) return NextResponse.json({ error: "bad MCP URL" }, { status: 500 });
  try {
    const upstream = await fetch(`${base}/api/v1/plugin-entries`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: `MCP unreachable: ${err instanceof Error ? err.message : err}` },
      { status: 502 },
    );
  }
}
