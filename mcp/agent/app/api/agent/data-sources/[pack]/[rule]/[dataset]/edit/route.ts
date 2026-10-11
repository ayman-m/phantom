/**
 * PUT /api/agent/data-sources/{pack}/{rule}/{dataset}/edit
 *
 * SP-4 — edit a data source's how_to_use prose and/or schema
 * fields. Thin proxy to the MCP at
 * /api/v1/data-sources/{pack}/{rule}/{dataset}/edit.
 *
 * Each save creates a version (overlay); the pristine original is
 * preserved as version 1. The file on disk is never mutated. Body (all
 * optional): { how_to_use?: string, fields?: object[], note?: string }.
 * Returns the MCP's JSON verbatim — { ok, version, data_source_id } on
 * success, or { ok: false, error } (4xx) on validation failure.
 *
 * Auth: session-cookie via middleware.ts, same as the rest of
 * /api/agent/data-sources/*.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string; rule: string; dataset: string }>;
}

export async function PUT(request: NextRequest, { params }: RouteParams) {
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
    'edit',
  ].join('/');

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}`, {
      method: 'PUT',
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
