/**
 * GET /api/agent/data-sources/{pack}/{rule}/{dataset}/versions
 *
 * SP-5 — list a data source's version history (metadata only). Thin
 * proxy to the MCP at /api/v1/data-sources/{pack}/{rule}/{dataset}/versions.
 * Returns { ok, versions: [{version, author, note, created_at, is_current}],
 * data_source_id }. Empty list when the source has never been edited.
 *
 * Auth: session-cookie via middleware.ts.
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
    'versions',
  ].join('/');

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}`, {
      headers: { Authorization: `Bearer ${r.token}` },
      cache: 'no-store',
    });
  } catch (err) {
    return NextResponse.json(
      { error: 'MCP unreachable', detail: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }

  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload ?? { error: `MCP returned ${upstream.status}` }, {
    status: upstream.status,
  });
}
