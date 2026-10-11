/**
 * GET /api/agent/data-sources
 *
 * Thin proxy to /api/v1/data-sources on the MCP side.
 *
 * Lists installed vendor schemas (data
 * sources) the operator has installed from Cortex content packs.
 *
 * Query params:
 *   filter — optional case-insensitive substring; matches pack_name OR
 *            dataset_name OR rule_name OR pack_description on the MCP side.
 *
 * Response shape (passthrough from MCP):
 *   { data_sources: [...], count: number, filter: string | null }
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const filter = request.nextUrl.searchParams.get('filter');
  const upstreamUrl = filter
    ? `${r.base}/api/v1/data-sources?filter=${encodeURIComponent(filter)}`
    : `${r.base}/api/v1/data-sources`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
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
