/**
 * GET /api/agent/marketplace/catalog/user
 *
 * The marketplace cards for connectors the operator uploaded.
 *
 * `/api/marketplace/connectors` serves the bundle connectors from a curated
 * list and cannot see anything under /app/data/user_connectors. The MCP's
 * marketplace catalogue (`GET /api/v1/marketplace`) can: each origin "user"
 * entry carries a `detail` object (image, config schema, secret slots, tools).
 * This route maps those entries to the same card shape
 * (`lib/connector-spec.ts`), so `listMarketplaceConnectors()` can append them
 * to the grid. It lives under /api/agent so the session gate applies; the
 * curated route stays public because it serves only bundle data.
 *
 * Response: an array of MarketplaceConnector (empty when nothing is uploaded).
 * MCP unreachable: 502, which the client treats as "no uploaded connectors".
 */

import { NextResponse } from 'next/server';

import { userConnectorCard, type UserCatalogueRow } from '@/lib/connector-spec';
import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/marketplace`, {
      headers: { Authorization: `Bearer ${r.token}` },
      cache: 'no-store',
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: 'MCP unreachable',
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }
  if (!upstream.ok) {
    return NextResponse.json(
      { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  const payload = (await upstream.json().catch(() => null)) as {
    connectors?: Array<UserCatalogueRow & { origin?: string }>;
  } | null;
  const rows = Array.isArray(payload?.connectors) ? payload.connectors : [];
  return NextResponse.json(
    rows
      .filter((row) => row.origin === 'user' && typeof row.id === 'string')
      .map((row) => userConnectorCard(row)),
  );
}
