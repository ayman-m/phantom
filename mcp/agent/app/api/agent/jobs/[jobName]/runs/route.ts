/**
 * Per-job run-history proxy — forwards GET /api/v1/jobs/{name}/runs.
 *
 * Returns the recent run history (paginated via ?limit=N). Each entry
 * has fired_at, finished_at, status, duration_ms, error, and the full
 * result payload (truncated by the MCP if large). Useful for showing
 * "last 10 runs of this scheduled job" in the UI and for debugging
 * scheduler dispatches that didn't behave as expected.
 *
 * Was missing pre-this-route: GET requests on /api/agent/jobs/<name>/
 * runs hit the [action] catch-all (POST-only) and got 405 Method Not
 * Allowed. The [action] route handles verb endpoints (run/enable/
 * disable); /runs is a noun and deserves its own path.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobName: string }> },
) {
  const { jobName } = await params;
  return proxyToMcp(
    request,
    `/api/v1/jobs/${encodeURIComponent(jobName)}/runs`,
  );
}
