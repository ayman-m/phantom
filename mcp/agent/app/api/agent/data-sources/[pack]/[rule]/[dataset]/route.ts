/**
 * GET    /api/agent/data-sources/{pack}/{rule}/{dataset}
 * DELETE /api/agent/data-sources/{pack}/{rule}/{dataset}
 *
 * Thin proxy to MCP.
 *
 * The composite path uses literal slashes (not URL-encoded composite
 * IDs) because the operator-facing reality maps one-to-one:
 *   FortiGate / FortiGate_1_3 / fortinet_fortigate_raw
 * That said, individual path segments are URL-encoded on the proxy
 * hop so any operator pack name containing a space or special char
 * round-trips correctly.
 *
 * GET returns the summary row (no fields, no XDM mappings).
 * GET /schema (sibling file) returns the expanded form.
 * DELETE uninstalls; cascade-drops dependent fields + xdm_mappings.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ pack: string; rule: string; dataset: string }>;
}

async function proxy(
  method: 'GET' | 'DELETE',
  params: { pack: string; rule: string; dataset: string },
): Promise<NextResponse> {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const path = [
    encodeURIComponent(params.pack),
    encodeURIComponent(params.rule),
    encodeURIComponent(params.dataset),
  ].join('/');

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}`, {
      method,
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

export async function GET(_request: NextRequest, { params }: RouteParams) {
  return proxy('GET', await params);
}

export async function DELETE(_request: NextRequest, { params }: RouteParams) {
  return proxy('DELETE', await params);
}
