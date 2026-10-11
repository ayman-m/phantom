/**
 * KB-scoped semantic search proxy. Forwards POST
 * /api/agent/knowledge/{name}/search → /api/v1/kbs/{name}/search.
 *
 * Body shape: { query: string, limit?: number, category?: string,
 *              min_score?: number }
 * Response:   { results: [{...doc, score}], count }
 *
 * Embedding goes through whatever the MCP wired at boot — Vertex
 * text-embedding-004 (768d) when the operator has supplied vertex
 * creds; TextHashEmbedder fallback otherwise.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  return proxyToMcp(
    request,
    `/api/v1/kbs/${encodeURIComponent(name)}/search`,
  );
}
