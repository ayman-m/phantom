/**
 * Session-end proxy — POST /api/v1/sessions/{id}/end.
 *
 * Marks `ended_at = now()` without deleting the session or its messages.
 * Useful when the operator wants to "close" a chat (e.g. for archival
 * or to stop further appends) but still browse it later.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToMcp(
    request,
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/end`,
  );
}
