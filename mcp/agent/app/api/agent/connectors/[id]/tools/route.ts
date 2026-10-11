/**
 * GET /api/agent/connectors/{id}/tools
 *
 * Proxies to /api/v1/connectors/{id}/tools on the MCP. Lists every tool
 * the connector ships, with optional per-instance disabled state when
 * ?instance_id=<id> is supplied.
 *
 * Used by the /connectors instance-detail Tools tab.
 */

import { NextRequest, NextResponse } from "next/server";

import { resolveMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(request: NextRequest, ctx: RouteContext) {
  const { id } = await ctx.params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const instanceId = request.nextUrl.searchParams.get("instance_id");
  const qs = instanceId ? `?instance_id=${encodeURIComponent(instanceId)}` : "";
  const upstreamUrl = `${r.base}/api/v1/connectors/${encodeURIComponent(id)}/tools${qs}`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      headers: { Authorization: `Bearer ${r.token}` },
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      { error: "MCP unreachable", detail: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }

  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload ?? { error: `MCP returned ${upstream.status}` }, {
    status: upstream.status,
  });
}
