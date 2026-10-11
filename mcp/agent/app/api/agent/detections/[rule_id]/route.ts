/**
 * Single detection rule summary proxy.
 *
 * GET /api/agent/detections/{rule_id}
 *   Returns: { rule: {...}, fires: {count, last_seen, ...} }
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
    `/api/v1/detections/${encodeURIComponent(rule_id)}`,
  );
}
