/**
 * MITRE technique coverage proxy.
 *
 * GET /api/agent/detections/coverage/techniques
 *   Returns aggregated detection coverage keyed by MITRE T-code:
 *     { techniques: [{ technique: "T1059.001", rule_count: N, fire_count: M, ...}], count }
 *
 * Used by the /observability/detections page's "Coverage" tab.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/detections/coverage/techniques');
}
