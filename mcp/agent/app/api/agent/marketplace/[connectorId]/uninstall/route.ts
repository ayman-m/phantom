/**
 * DELETE /api/agent/marketplace/{connectorId}/uninstall
 *
 * Thin proxy to the MCP marketplace surface.
 *
 * The install state lives in MCP (see
 * `bundles/spark/mcp/src/api/marketplace.py:uninstall_connector`),
 * including the instances-presence check. This handler is a
 * forwarder that preserves the UI's response contract.
 *
 * Body: empty, connectorId in path.
 *
 * Response shape preserved:
 *   200 { connector_id, uninstalled: true }
 *   409 { error, connector_id, instances_count } when instances exist
 *   404 { error } when connector not installed
 *   401/502 on auth/transport errors
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ connectorId: string }> },
) {
  const { connectorId } = await params;
  if (!connectorId) {
    return NextResponse.json(
      { error: 'connectorId path segment is required' },
      { status: 400 },
    );
  }

  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${r.base}/api/v1/marketplace/${encodeURIComponent(connectorId)}/uninstall`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${r.token}` },
        cache: 'no-store',
      },
    );
  } catch (err) {
    return NextResponse.json(
      {
        error: 'MCP unreachable',
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  const upstreamPayload = await upstream.json().catch(() => null);

  if (!upstream.ok) {
    // 409 from MCP carries instances_count + error message; pass it
    // through verbatim so the UI's toast can quote the MCP-side text.
    return NextResponse.json(
      upstreamPayload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  // Preserve the success shape the UI expects — the UI's marketplace
  // client checks `result.uninstalled === true`.
  return NextResponse.json({
    connector_id: connectorId,
    uninstalled: true,
    upstream: upstreamPayload,
  });
}
