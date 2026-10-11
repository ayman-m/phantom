/**
 * Per-job action proxy — forwards POST /api/v1/jobs/{name}/{run|enable|disable}
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobName: string; action: string }> },
) {
  const { jobName, action } = await params;
  if (!['run', 'enable', 'disable'].includes(action)) {
    return new Response(JSON.stringify({ error: 'unknown action' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  return proxyToMcp(
    request,
    `/api/v1/jobs/${encodeURIComponent(jobName)}/${action}`,
  );
}
