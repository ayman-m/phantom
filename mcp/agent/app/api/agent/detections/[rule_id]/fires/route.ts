/**
 * Detection fires for one rule.
 *
 * GET /api/agent/detections/{rule_id}/fires
 *   Query params (forwarded):
 *     - limit  (default 100)
 *     - since  (ISO-8601 timestamp; only fires after this)
 *   Returns: { fires: [...], count: N }
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ rule_id: string }> },
) {
  const { rule_id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/detections/${encodeURIComponent(rule_id)}/fires`,
  );
}
