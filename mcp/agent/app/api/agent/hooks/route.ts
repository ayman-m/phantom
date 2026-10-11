/**
 * Hooks list/upsert proxy.
 *
 * Thin passthrough to the MCP's `/api/v1/hooks` endpoint. The
 * chat-route doesn't go through this proxy (it uses `callMcpServer`
 * with a server-side token); this exists for the `/settings/hooks`
 * UI page so the browser can read and write hook records.
 *
 *   GET  /api/agent/hooks?event=<name> → { hooks, count }
 *   POST /api/agent/hooks               → upsert (create when id absent)
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

export async function GET(request: Request) {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  const url = new URL(request.url);
  try {
    const upstream = await fetch(`${r.base}/api/v1/hooks${url.search}`, {
      headers: { Authorization: `Bearer ${r.token}` },
      signal: AbortSignal.timeout(10000),
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

export async function POST(request: Request) {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  try {
    const upstream = await fetch(`${r.base}/api/v1/hooks`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${r.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
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
