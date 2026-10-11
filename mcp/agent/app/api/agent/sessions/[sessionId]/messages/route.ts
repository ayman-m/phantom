/**
 * Per-session messages proxy. GET fetches history, POST appends.
 */

import { NextResponse } from 'next/server';

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

async function resolveMcp() {
  const config = await getEffectiveRuntimeConfig();
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  const base = deriveMcpBaseUrl(mcpUrl);
  return { base, mcpToken };
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  const { base, mcpToken } = await resolveMcp();
  if (!mcpToken)
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  if (!base)
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  // Forward the incoming query string (limit, offset, ascending) to
  // the MCP endpoint. Dropping it would break both explicit pagination AND
  // the `?ascending=true` signal from getSessionTranscript / getSessionTelemetry. The MCP-side
  // default of "no limit" still applies when no `?limit=` is passed.
  const incomingUrl = new URL(request.url);
  const qs = incomingUrl.search; // includes the leading "?" or is ""
  try {
    const r = await fetch(
      `${base}/api/v1/sessions/${encodeURIComponent(sessionId)}/messages${qs}`,
      {
        headers: { Authorization: `Bearer ${mcpToken}` },
        signal: AbortSignal.timeout(10000),
      },
    );
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

export async function POST(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  const { base, mcpToken } = await resolveMcp();
  if (!mcpToken)
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  if (!base)
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  try {
    const body = await request.text();
    const r = await fetch(
      `${base}/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${mcpToken}`,
          'Content-Type': 'application/json',
        },
        body,
        signal: AbortSignal.timeout(10000),
      },
    );
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
