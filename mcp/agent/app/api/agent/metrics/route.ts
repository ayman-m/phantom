/**
 * Metrics proxy — forwards GET /api/agent/metrics → MCP /api/v1/metrics.
 * Returns Prometheus text format. Used by /observability/metrics and the
 * overview tile.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/metrics');
}
