/**
 * GET /api/agent/data-sources/user/{id}/logo
 *
 * Streams the inline base64 logo from a user-uploaded data_source.yaml.
 * Used by the VendorCard's icon panel for origin=user rows.
 *
 * Proxies to /api/v1/data-sources/user/{id}/logo.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(_request: NextRequest, ctx: RouteContext) {
  const { id } = await ctx.params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${r.base}/api/v1/data-sources/user/${encodeURIComponent(id)}/logo`,
      {
        headers: { Authorization: `Bearer ${r.token}` },
        cache: 'no-store',
      },
    );
  } catch (err) {
    return NextResponse.json(
      { error: 'MCP unreachable', detail: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text().catch(() => '');
    return NextResponse.json(
      { error: text || `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  // Stream the body through with the upstream's content-type
  const body = await upstream.arrayBuffer();
  return new NextResponse(body, {
    status: 200,
    headers: {
      'Content-Type': upstream.headers.get('content-type') ?? 'image/svg+xml',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
