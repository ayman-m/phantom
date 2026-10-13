/**
 * Jobs proxy — forwards to /api/v1/jobs.
 *
 * GET   → list all jobs (manifest + runtime). Pass ?include_removed=1 to
 *         include manifest jobs that were removed from manifest.yaml since
 *         the last reconciliation.
 * POST  → create a new runtime job. Body: {name, cron, timezone?, action,
 *         enabled?}. The MCP tags it with source='runtime' so it survives
 *         manifest reconciliation untouched.
 *
 * `model_id` is checked before the job is saved: it must name a model the
 * registry accepts (a canonical "provider/model" ref, or a bare id that one
 * configured provider offers) and is stored canonical. An unknown, retired or
 * unconfigured model answers 400 with suggestions and the job is not saved.
 * An empty `model_id` means "no override". The MCP stays permissive; a job
 * created some other way (the agent's jobs_create tool) is caught at dispatch.
 */

import { NextResponse } from 'next/server';

import { proxyToMcp } from '@/lib/mcp-proxy';
import { checkModelWrite } from '@/lib/model-registry-server';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/jobs');
}

export async function POST(request: Request) {
  const checked = await checkModelWrite('job', await request.text());
  if (!checked.ok) return NextResponse.json(checked.body, { status: checked.status });
  return proxyToMcp(request, '/api/v1/jobs', { body: checked.body });
}
