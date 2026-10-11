/**
 * GET /api/agent/data-sources/catalog
 *
 * Thin proxy to /api/v1/data-sources/catalog. Returns the rolled-up
 * catalog of available data sources. Query params (passthrough):
 *   xsiam_only      — default true
 *   include_rawlog  — default false
 *   pack_limit      — default 0 (all)
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';
// Allow long fetches (Browse tab cold-start hits GitHub).
export const maxDuration = 120;

export async function GET(request: NextRequest) {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const passthrough = ['xsiam_only', 'include_rawlog', 'pack_limit', 'origin'];
  const usp = new URLSearchParams();
  for (const key of passthrough) {
    const v = request.nextUrl.searchParams.get(key);
    if (v !== null) usp.set(key, v);
  }
  const qs = usp.toString();
  const upstreamUrl = qs
    ? `${r.base}/api/v1/data-sources/catalog?${qs}`
    : `${r.base}/api/v1/data-sources/catalog`;

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
