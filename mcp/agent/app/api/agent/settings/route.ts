/**
 * Settings proxy — used by SparkSettingsEditor to load + save the
 * runtime overridable settings declared in manifest.settings.
 *
 *   GET  /api/agent/settings    → describe-store snapshot
 *                                  {defaults, overridable, effective, overrides}
 *   PUT  /api/agent/settings    → bulk set/clear
 *                                  body: {updates, clear, actor}
 *
 * Both endpoints proxy to the embedded MCP's /api/v1/settings,
 * attaching MCP_TOKEN server-side so the browser doesn't need to
 * hold the bundle-internal bearer.
 */

import { NextResponse } from 'next/server';

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

async function _resolveMcp(): Promise<{ base: string; token: string } | NextResponse> {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken)
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base)
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  return { base, token: mcpToken };
}

export async function GET() {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const upstream = await fetch(`${r.base}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${r.token}` },
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'settings GET failed' },
      { status: 502 },
    );
  }
}

export async function PUT(request: Request) {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const body = await request.text();
    const upstream = await fetch(`${r.base}/api/v1/settings`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${r.token}`,
        'Content-Type': 'application/json',
      },
      body,
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'settings PUT failed' },
      { status: 502 },
    );
  }
}
