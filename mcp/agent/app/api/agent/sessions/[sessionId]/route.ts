/**
 * Per-session CRUD proxy — forwards to /api/v1/sessions/{id}.
 *
 * GET    → fetch one session (id, title, started_at, ended_at, meta).
 * PATCH  → partial update {title?, metadata?, replace_metadata?:false}.
 *          By default metadata is shallow-merged; pass replace_metadata
 *          to overwrite the whole blob.
 * DELETE → hard-delete the session and all its messages.
 *
 * The session-end endpoint (which marks ended_at without deleting) lives
 * in end/route.ts as a verb endpoint. Export lives in export/route.ts.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToMcp(
    request,
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToMcp(
    request,
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyToMcp(
    request,
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
  );
}
