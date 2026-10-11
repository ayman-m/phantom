/**
 * /api/agent/data-sources/user/{id}
 *
 *   GET    → single user data source (catalog row + full YAML doc)
 *   PUT    → edit an existing user upload (body: yaml|doc + accept_token +
 *            vendor_choice; same shape as POST /api/agent/data-sources/user
 *            but the route's `id` is the canonical target)
 *   DELETE → remove user upload (cascades uninstall from data_sources_store)
 *
 * Proxies to /api/v1/data-sources/user/{id}.
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
      `${r.base}/api/v1/data-sources/user/${encodeURIComponent(id)}`,
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

  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload ?? { error: `MCP returned ${upstream.status}` }, {
    status: upstream.status,
  });
}

export async function PUT(request: NextRequest, ctx: RouteContext) {
  const { id } = await ctx.params;
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
    upstream = await fetch(
      `${r.base}/api/v1/data-sources/user/${encodeURIComponent(id)}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${r.token}`,
        },
        body: JSON.stringify(body),
        cache: 'no-store',
      },
    );
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

export async function DELETE(_request: NextRequest, ctx: RouteContext) {
  const { id } = await ctx.params;
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${r.base}/api/v1/data-sources/user/${encodeURIComponent(id)}`,
      {
        method: 'DELETE',
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

  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload ?? { error: `MCP returned ${upstream.status}` }, {
    status: upstream.status,
  });
}
