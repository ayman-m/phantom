/**
 * Memory semantic-search proxy. Forwards POST /api/agent/memory/search →
 * MCP's /api/v1/memories/search with body { query, limit, scope }.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/memories/search');
}
