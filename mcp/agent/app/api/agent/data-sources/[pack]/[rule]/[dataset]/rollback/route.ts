/**
 * POST /api/agent/data-sources/{pack}/{rule}/{dataset}/rollback
 *
 * SP-5 — roll a data source back to a prior version. Thin proxy to the
 * MCP. Body: { version: number }. Non-destructive — the MCP copies the target
 * version forward as a new current version; history is preserved. Returns
 * { ok, version, data_source_id } (the new current version) or { ok: false,
 * error } (4xx) on unknown version / no history.
 *
 * Auth: session-cookie via middleware.ts.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string; rule: string; dataset: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { pack, rule, dataset } = await params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const path = [
    encodeURIComponent(pack),
    encodeURIComponent(rule),
    encodeURIComponent(dataset),
    'rollback',
  ].join('/');

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${r.token}`,
      },
      body: JSON.stringify(body),
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
