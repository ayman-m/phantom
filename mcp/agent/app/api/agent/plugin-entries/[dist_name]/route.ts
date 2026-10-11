/**
 * Plugin uninstall proxy.
 *
 *   DELETE /api/agent/plugin-entries/{dist_name}
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

export async function DELETE(
  _req: Request,
  ctx: { params: Promise<{ dist_name: string }> },
) {
  const { dist_name } = await ctx.params;
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

  const upstream = await fetch(
    `${base}/api/v1/plugin-entries/${encodeURIComponent(dist_name)}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
