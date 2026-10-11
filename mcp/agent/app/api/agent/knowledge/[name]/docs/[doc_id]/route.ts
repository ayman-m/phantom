/**
 * Single-doc fetch proxy. Forwards GET
 * /api/agent/knowledge/{name}/docs/{doc_id} →
 * /api/v1/kbs/{name}/docs/{doc_id}. The MCP audits this read
 * (ACTION_KB_DOC_READ) — useful for "what did the operator look at?".
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ name: string; doc_id: string }> },
) {
  const { name, doc_id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/kbs/${encodeURIComponent(name)}/docs/${encodeURIComponent(doc_id)}`,
  );
}
