/**
 * Per-id hook passthrough.
 *
 *   GET    /api/agent/hooks/{id} → fetch one
 *   PATCH  /api/agent/hooks/{id} → partial update (commonly enabled toggle)
 *   DELETE /api/agent/hooks/{id} → remove
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

async function _proxy(
  request: Request,
  id: string,
  method: "GET" | "PATCH" | "DELETE",
): Promise<NextResponse> {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  let body: string | undefined;
  if (method === "PATCH") {
    try {
      body = await request.text();
    } catch {
      return NextResponse.json(
        { error: "invalid body" },
        { status: 400 },
      );
    }
  }
  try {
    const upstream = await fetch(
      `${r.base}/api/v1/hooks/${encodeURIComponent(id)}`,
      {
        method,
        headers: {
          Authorization: `Bearer ${r.token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body,
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

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return _proxy(request, id, "GET");
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return _proxy(request, id, "PATCH");
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return _proxy(request, id, "DELETE");
}
