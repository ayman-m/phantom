/**
 * GET /api/agent/data-sources/logo/{pack}
 *
 * Thin proxy that streams a vendor logo's bytes from the bundled
 * catalog. Cache-Control header is forwarded so the browser caches
 * per-pack. Returns 404 when the pack isn't in the catalog OR has
 * no logo.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { pack } = await params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  // Forward ?theme= query to the MCP route
  const themeParam = request.nextUrl.searchParams.get('theme');
  const theme = themeParam === 'dark' ? 'dark' : 'light';
  const upstreamUrl = `${r.base}/api/v1/data-sources/logo/${encodeURIComponent(pack)}?theme=${theme}`;

  let upstream: Response;
  try {
    upstream = await fetch(
      upstreamUrl,
      {
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

  if (!upstream.ok) {
    const errPayload = await upstream.json().catch(() => null);
    return NextResponse.json(
      errPayload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  // Stream the bytes through; preserve Content-Type + Cache-Control
  const headers = new Headers();
  const ct = upstream.headers.get('Content-Type');
  if (ct) headers.set('Content-Type', ct);
  const cc = upstream.headers.get('Cache-Control');
  if (cc) headers.set('Cache-Control', cc);
  return new NextResponse(upstream.body, { status: 200, headers });
}
