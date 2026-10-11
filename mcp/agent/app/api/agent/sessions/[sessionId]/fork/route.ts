/**
 * Session fork proxy.
 *
 * Thin passthrough to MCP's POST /api/v1/sessions/{session_id}/fork.
 * The /chat session sidebar's Fork menu button hits this route to
 * branch a new session from the current one.
 *
 *   POST /api/agent/sessions/{id}/fork
 *     body: { from_message_id?, title?, user? }
 *     → { session: { id, ... } }
 */

import { NextResponse } from "next/server";

import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId: id } = await ctx.params;
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
  let body: unknown = {};
  try {
    body = await req.json();
  } catch {
    // Body is optional — POST without body forks the full
    // conversation (no from_message_id cut-off).
    body = {};
  }
  const r = await fetch(
    `${base}/api/v1/sessions/${encodeURIComponent(id)}/fork`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body ?? {}),
    },
  );
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}
