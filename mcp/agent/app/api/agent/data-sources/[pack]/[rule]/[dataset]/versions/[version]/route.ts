/**
 * GET /api/agent/data-sources/{pack}/{rule}/{dataset}/versions/{version}
 *
 * SP-5 — fetch one version's full content (incl. yaml_snapshot). Thin
 * proxy to the MCP. 404 if the version doesn't exist for this source.
 *
 * Auth: session-cookie via middleware.ts.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string; rule: string; dataset: string; version: string }>;
}

export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { pack, rule, dataset, version } = await params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const path = [
    encodeURIComponent(pack),
    encodeURIComponent(rule),
    encodeURIComponent(dataset),
    'versions',
    encodeURIComponent(version),
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
