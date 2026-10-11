/**
 * Sessions list proxy. Forwards query params (active_only, user, limit)
 * to the MCP's /api/v1/sessions, adding bearer auth from the agent's env.
 */

import { NextResponse } from 'next/server';

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const config = await getEffectiveRuntimeConfig();
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken) {
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  }
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) {
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  }
  const url = new URL(request.url);
  const target = `${base}/api/v1/sessions${url.search}`;
  try {
    const r = await fetch(target, {
      headers: { Authorization: `Bearer ${mcpToken}` },
      signal: AbortSignal.timeout(10000),
    });
    // Unwrap MCP's `{sessions: [...], count: N}` envelope to a plain
    // array so the agent's `listRequest` helper (which understands
    // `T[]` or `{data: [...]}` envelopes — but not `{sessions: [...]}`)
    // can consume it. Pass through non-2xx responses as-is.
    if (!r.ok) {
      const text = await r.text();
      return new NextResponse(text, {
        status: r.status,
        headers: {
          'Content-Type':
            r.headers.get('content-type') ?? 'application/json',
        },
      });
    }
    const body = (await r.json().catch(() => null)) as {
      sessions?: unknown[];
    } | null;
    const sessions = Array.isArray(body?.sessions) ? body!.sessions : [];
    return NextResponse.json(sessions, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'fetch failed' },
      { status: 502 },
    );
  }
}

export async function POST(request: Request) {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken) {
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  }
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) {
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  }
  try {
    const body = await request.text();
    const r = await fetch(`${base}/api/v1/sessions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${mcpToken}`,
        'Content-Type': 'application/json',
      },
      body,
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
