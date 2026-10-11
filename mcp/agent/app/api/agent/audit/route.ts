/**
 * Audit query proxy — used by the SparkActivityTimeline component.
 */

import { NextResponse } from 'next/server';

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
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
  const url = new URL(request.url);
  try {
    const r = await fetch(`${base}/api/v1/audit${url.search}`, {
      headers: { Authorization: `Bearer ${mcpToken}` },
      signal: AbortSignal.timeout(10000),
    });
    const text = await r.text();
    return new NextResponse(text, {
      status: r.status,
      headers: {
        'Content-Type':
          r.headers.get('content-type') ?? 'application/json',
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'fetch failed' },
      { status: 502 },
    );
  }
}
