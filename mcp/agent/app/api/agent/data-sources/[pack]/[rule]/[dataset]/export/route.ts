/**
 * GET /api/agent/data-sources/{pack}/{rule}/{dataset}/export
 *
 * Download the pack's raw `data_source.yaml`. Thin proxy
 * to the MCP at /api/v1/data-sources/{pack}/{rule}/{dataset}/export.
 * The UI's Export button on each Browse-tab row + the drawer's Export
 * action hit this.
 *
 * Streams the upstream response body verbatim so the YAML's
 * Content-Disposition / Content-Type headers carry through and the
 * browser triggers a download instead of rendering the file.
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

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { pack, rule, dataset } = await params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const path = [
    encodeURIComponent(pack),
    encodeURIComponent(rule),
    encodeURIComponent(dataset),
    'export',
  ].join('/');

  // SP-6 — forward an optional ?version=n so operators can export a
  // specific historical version (default = current).
  const version = request.nextUrl.searchParams.get('version');
  const query = version ? `?version=${encodeURIComponent(version)}` : '';

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/${path}${query}`, {
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

  if (!upstream.ok) {
    const payload = await upstream.json().catch(() => null);
    return NextResponse.json(
      payload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  // Stream the YAML body through. Preserve Content-Disposition (sets
  // the download filename) + Content-Type. Strip hop-by-hop headers
  // Next.js handles for us — no need to forward Transfer-Encoding or
  // Connection.
  const body = await upstream.text();
  const filename =
    upstream.headers.get('content-disposition') ??
    // Filename is `<dataset>.yaml`, matching what the MCP
    // sends in its Content-Disposition. The fallback only kicks in
    // when the upstream header is missing; we keep the shapes aligned.
    `attachment; filename="${dataset}.yaml"`;
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type':
        upstream.headers.get('content-type') ?? 'application/x-yaml; charset=utf-8',
      'Content-Disposition': filename,
      'Cache-Control': 'no-store',
    },
  });
}
