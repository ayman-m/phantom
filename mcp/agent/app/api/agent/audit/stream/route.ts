/**
 * SSE pass-through for the MCP's audit stream. The /activity page
 * subscribes via EventSource (or a fetch + ReadableStream). The
 * Next.js proxy injects the bearer token so the browser never holds
 * the MCP_TOKEN.
 *
 * runtime: 'nodejs' is required for proper streaming on Vercel /
 * standalone Next; the default 'edge' runtime would buffer the whole
 * response. We also explicitly forward request.signal to abort the
 * upstream fetch when the client disconnects, so we don't leak open
 * sqlite poll loops on the MCP side.
 */
import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: Request) {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken) {
    return new Response('MCP_TOKEN not configured', { status: 503 });
  }
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) {
    return new Response('bad MCP URL', { status: 500 });
  }

  const url = new URL(request.url);
  const upstreamUrl = `${base}/api/v1/audit/stream${url.search}`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      headers: { Authorization: `Bearer ${mcpToken}` },
      signal: request.signal,
    });
  } catch (err) {
    return new Response(
      err instanceof Error ? err.message : 'upstream fetch failed',
      { status: 502 },
    );
  }

  if (!upstream.ok || !upstream.body) {
    return new Response(`upstream ${upstream.status}`, {
      status: upstream.status || 502,
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
    },
  });
}
