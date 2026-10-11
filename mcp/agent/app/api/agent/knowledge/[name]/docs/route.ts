/**
 * KB document list proxy. Forwards GET /api/agent/knowledge/{name}/docs?...
 * → MCP's /api/v1/kbs/{name}/docs. The MCP returns documents WITHOUT
 * the `content` field by default (browse view); the detail proxy at
 * /docs/[doc_id] does include it for the drawer.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  return proxyToMcp(
    request,
    `/api/v1/kbs/${encodeURIComponent(name)}/docs`,
  );
}
