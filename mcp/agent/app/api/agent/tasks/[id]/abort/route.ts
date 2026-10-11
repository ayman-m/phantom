/**
 * Task abort proxy.
 *
 *   POST /api/agent/tasks/{id}/abort → mark task aborted
 *
 * The worker is expected to poll its task status periodically and
 * bail when it sees `status === 'aborted'`. This endpoint just
 * flips the bit; it doesn't send signals to subprocesses.
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

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  let body: string | undefined;
  try {
    body = await request.text();
  } catch {
    body = "";
  }
  try {
    const upstream = await fetch(
      `${r.base}/api/v1/tasks/${encodeURIComponent(id)}/abort`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${r.token}`,
          "Content-Type": "application/json",
        },
        body: body || "{}",
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
