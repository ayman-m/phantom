/**
 * GET /api/agent/data-sources/{pack}/{rule}/{dataset}/schema
 *
 * Thin proxy to MCP. Returns the expanded data source row including
 * the full field inventory + XDM mappings.
 *
 * The UI drill-down view consumes this to render the
 * field table. List view (sibling /route.ts) uses the lighter row
 * shape that omits the field details.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string; rule: string; dataset: string }>;
}

export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { pack, rule, dataset } = await params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const path = [
    encodeURIComponent(pack),
    encodeURIComponent(rule),
    encodeURIComponent(dataset),
    'schema',
  ].join('/');

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}`, {
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

  const payload = await upstream.json().catch(() => null);
  if (!upstream.ok) {
    return NextResponse.json(
      payload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }
  return NextResponse.json(payload);
}
