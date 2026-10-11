/**
 * POST /api/agent/marketplace/install
 *
 * Thin proxy to the MCP marketplace surface.
 *
 * The canonical install state lives in MCP
 * (`bundles/spark/mcp/src/usecase/marketplace_store.py` →
 *  `api/marketplace.py`) so there's ONE storage home for it, per
 * CLAUDE.md's "Canonical-state discipline" rule.
 *
 * Body shape, as the UI client (`lib/api/marketplace.ts`) sends it:
 *   { connector_id: string, version?: string }
 *
 * Response shape preserves the client-visible fields:
 *   { id, connector_id, version, execution_mode, install }
 *
 * On the MCP side the install is idempotent; calling twice returns
 * the same row. Origin (bundle vs user) is derived from the
 * catalogue at first install — not operator-supplied — to prevent a
 * client lying about a connector's provenance.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface InstallRequest {
  connector_id?: unknown;
  version?: unknown;
}

export async function POST(request: NextRequest) {
  let body: InstallRequest;
  try {
    body = (await request.json()) as InstallRequest;
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const connectorId =
    typeof body.connector_id === 'string' ? body.connector_id.trim() : '';
  if (!connectorId) {
    return NextResponse.json(
      { error: 'connector_id is required (string)' },
      { status: 400 },
    );
  }

  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${r.base}/api/v1/marketplace/${encodeURIComponent(connectorId)}/install`,
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
    // Pass-through error shape (status + body) so the UI can render
    // the MCP's explanation verbatim — e.g. 404 "connector not found
    // in catalogue".
    return NextResponse.json(
      upstreamPayload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  const install =
    upstreamPayload && typeof upstreamPayload === 'object'
      ? (upstreamPayload as Record<string, unknown>).install
      : null;
  const version =
    install &&
    typeof install === 'object' &&
    typeof (install as Record<string, unknown>).version === 'string'
      ? (install as Record<string, unknown>).version
      : 'bundled';

  // Response shape mirrors the contract the UI client expects.
  // `execution_mode: "embedded"` is a legacy field the UI's version-
  // comparison logic treats as "no upgrade available"; preserved as a
  // stable sentinel.
  return NextResponse.json({
    id: connectorId,
    connector_id: connectorId,
    version,
    execution_mode: 'embedded',
    install,
  });
}
