/**
 * Bench runs list/start proxy.
 *
 * Thin passthrough to the MCP's /api/v1/bench/runs endpoint. The
 * /observability/bench page reads + writes here.
 *
 *   GET  /api/agent/bench/runs?limit=20  → { runs, count }
 *   POST /api/agent/bench/runs           → trigger a new run
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
  if (!mcpToken) {
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
  return { base, token: mcpToken };
}

export async function GET(req: Request) {
  const resolved = await _resolveMcp();
  if (resolved instanceof NextResponse) return resolved;
  const url = new URL(req.url);
  const limit = url.searchParams.get("limit") ?? "20";
  const r = await fetch(
    `${resolved.base}/api/v1/bench/runs?limit=${encodeURIComponent(limit)}`,
    {
      headers: { Authorization: `Bearer ${resolved.token}` },
      cache: "no-store",
    },
  );
  const body = await r.text();
  return new NextResponse(body, {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function POST(req: Request) {
  const resolved = await _resolveMcp();
  if (resolved instanceof NextResponse) return resolved;
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "body must be JSON" },
      { status: 400 },
    );
  }
  const r = await fetch(`${resolved.base}/api/v1/bench/runs`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${resolved.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}
