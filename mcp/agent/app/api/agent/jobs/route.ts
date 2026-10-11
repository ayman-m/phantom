/**
 * Jobs proxy — forwards to /api/v1/jobs.
 *
 * GET   → list all jobs (manifest + runtime). Pass ?include_removed=1 to
 *         include manifest jobs that were removed from manifest.yaml since
 *         the last reconciliation.
 * POST  → create a new runtime job. Body: {name, cron, timezone?, action,
 *         enabled?}. The MCP tags it with source='runtime' so it survives
 *         manifest reconciliation untouched.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/jobs');
}

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/jobs');
}
