/**
 * GET /api/agent/data-sources/inline-logo/{id}
 *
 * Streams the inline base64 logo from EITHER a bundled or user-uploaded
 * data_source.yaml. The catalog's `_compute_logo_url()` returns this
 * URL whenever the YAML carries an inline `logo:` block (regardless of
 * origin), so bundle YAMLs can ship self-contained SVGs without
 * touching the baked vendor_map / vendor_svgs tree.
 *
 * Resolution priority on the backend (data_source.yaml `_compute_logo_url`):
 *   1. inline-logo route (THIS route) — when YAML has `logo:` block
 *   2. user route — user origin, no inline logo (404s, vestigial)
 *   3. legacy vendor route — bundle origin, no inline logo, walks baked tree
 *
 * Proxies to /api/v1/data-sources/inline-logo/{id}.
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
      `${r.base}/api/v1/data-sources/inline-logo/${encodeURIComponent(id)}`,
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

  // Stream the body through with the upstream's content-type.
  // Cache-Control matches the upstream (immutable for inline-logo —
  // the YAML's logo bytes only change when the YAML itself changes).
  const body = await upstream.arrayBuffer();
  return new NextResponse(body, {
    status: 200,
    headers: {
      'Content-Type': upstream.headers.get('content-type') ?? 'image/svg+xml',
      'Cache-Control':
        upstream.headers.get('cache-control') ?? 'public, max-age=86400, immutable',
    },
  });
}
