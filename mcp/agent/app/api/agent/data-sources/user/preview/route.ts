/**
 * POST /api/agent/data-sources/user/preview
 *
 * Thin proxy to /api/v1/data-sources/user/preview. Validates an uploaded
 * data_source.yaml + runs the vendor similarity check; returns an
 * accept_token the operator passes to /user when committing.
 *
 * Body shape: { yaml: "<full text>" }  OR  { doc: {...parsed...} }
 *
 * Response shape (success):
 *   { ok: true, uploaded_vendor, uploaded_id, similarity_matches,
 *     bundle_collision, accept_token }
 *
 * Response shape (validation fail):
 *   { ok: false, errors: ["categories[0]: must be string", ...] }
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/user/preview`, {
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
