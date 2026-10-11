/**
 * Bench run detail proxy.
 *
 *   GET /api/agent/bench/runs/{run_id} → { run: { run_id, summary } }
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ run_id: string }> },
) {
  const { run_id } = await ctx.params;
  const config = await getEffectiveRuntimeConfig();
  const token =
    (config.MCP_TOKEN || "").trim() || process.env.MCP_TOKEN?.trim() || "";
  if (!token) {
    return NextResponse.json(
      { error: "MCP_TOKEN not configured" },
      { status: 503 },
    );
  }
  const mcpUrl =
    (config.MCP_URL || "").trim() ||
    process.env.MCP_URL?.trim() ||
    "http://phantom-mcp:8080/api/v1/stream/mcp";
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) {
    return NextResponse.json({ error: "bad MCP URL" }, { status: 500 });
  }
  const r = await fetch(
    `${base}/api/v1/bench/runs/${encodeURIComponent(run_id)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );
  const body = await r.text();
  return new NextResponse(body, {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}
