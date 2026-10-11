/**
 * Session-export proxy — GET /api/v1/sessions/{id}/export?format=...
 *
 * Returns the entire session (metadata + every message) in one of three
 * formats:
 *   - markdown (default) → human-readable, headers + per-message blocks
 *   - json               → structured, full fidelity (timestamps, meta)
 *   - yaml               → structured, requires PyYAML on the MCP side;
 *                          MCP responds 501 if not available
 *
 * The proxy preserves the upstream Content-Type header (text/markdown,
 * application/json, application/x-yaml) so the browser can offer a
 * sensible default download experience when the route is hit directly.
 *
 * Note: the timeout for export is the same 15s used by other proxies.
 * For very long chats this could be tight, but it's a reasonable cap
 * for an embedded sqlite store; revisit if export starts timing out.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToMcp(
    request,
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/export`,
  );
}
