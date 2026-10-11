/**
 * Knowledge-base index proxy. Forwards GET /api/agent/knowledge →
 * MCP's /api/v1/kbs (per-KB summary: name, doc_count, latest_loaded_at).
 *
 * Read-only by design — manifest.kbWrites is [], and the v1.2 spec
 * keeps KB content lifecycle in the bundle (edit + redeploy). A future
 * Tier-3 runtime-CRUD pass (mirroring the runtime jobs YAML pattern)
 * would add POST/PATCH/DELETE here; for now, the agent UI just lists.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/kbs');
}
