/**
 * DELETE /api/agent/marketplace/{connectorId}
 *
 * Thin proxy to MCP's DELETE /api/v1/marketplace/{id}: remove a connector the
 * operator uploaded (its install marker and /app/data/user_connectors/<id>/).
 * The MCP refuses a bundle connector (403 cannot_delete_bundle) and a
 * connector that still has instances (409 has_instances); both bodies are
 * passed through so the UI can quote them.
 *
 * This is the one place the UI deletes a connector. Uninstall (the sibling
 * `uninstall` route) only clears the install marker and keeps the connector
 * in the catalogue.
 *
 * Response: 200 { connector_id, deleted: true } | upstream error status + body.
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
      `${r.base}/api/v1/marketplace/${encodeURIComponent(connectorId)}`,
      {
        method: 'DELETE',
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
    return NextResponse.json(
      upstreamPayload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }
  return NextResponse.json({ connector_id: connectorId, deleted: true });
}
