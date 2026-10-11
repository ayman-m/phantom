/**
 * GET /api/agent/marketplace/{connectorId}/download
 *
 * Proxy to MCP's GET /api/v1/marketplace/{id}/download. Streams the
 * connector.yaml back to the caller with proper save-as headers so
 * the browser prompts a file save when the operator clicks the
 * Download button on a marketplace card.
 *
 * The MCP side handles bundle/user disambiguation + audits the
 * download as a `connector_downloaded` event. This proxy only
 * forwards the request + preserves the Content-Type + Content-
 * Disposition headers so the browser's save-as flow works.
 */

import { NextResponse } from "next/server";

import { resolveMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ connectorId: string }> },
) {
  const { connectorId } = await ctx.params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  try {
    const upstream = await fetch(
      `${r.base}/api/v1/marketplace/${encodeURIComponent(connectorId)}/download`,
      {
        headers: { Authorization: `Bearer ${r.token}` },
        cache: "no-store",
      },
    );
    // Forward headers the browser needs for save-as. Content-Type
    // tells the browser this is YAML, Content-Disposition triggers
    // the download prompt with a suggested filename.
    const contentType =
      upstream.headers.get("content-type") || "application/yaml";
    const contentDisposition =
      upstream.headers.get("content-disposition") ||
      `attachment; filename="${connectorId}.yaml"`;
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": contentDisposition,
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: `MCP unreachable: ${err instanceof Error ? err.message : err}` },
      { status: 502 },
    );
  }
}
