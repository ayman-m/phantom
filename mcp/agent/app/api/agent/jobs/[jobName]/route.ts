/**
 * Per-job CRUD proxy — forwards to /api/v1/jobs/{name}.
 *
 * GET    → fetch one job (manifest or runtime).
 * PATCH  → partial update {cron?, timezone?, action?, enabled?}. For
 *          manifest-source jobs, edits are applied at runtime but will
 *          revert to the manifest values on the next reconciliation
 *          (boot or manifest reload). The MCP returns the updated row.
 *          A `model_id` is checked against the model registry and stored
 *          canonical (400 with suggestions otherwise); `""` clears the
 *          override and an absent field leaves it as it is.
 * DELETE → hard-delete a runtime job (and its run history). For
 *          manifest jobs the MCP marks them removed=1 instead, so
 *          they show up in audit but stop firing.
 *
 * The /api/v1/jobs/{name}/{run|enable|disable} action endpoints live
 * in [action]/route.ts for consistency with how Spark splits "noun"
 * vs "verb" endpoints.
 */

import { NextResponse } from 'next/server';

import { proxyToMcp } from '@/lib/mcp-proxy';
import { checkModelWrite } from '@/lib/model-registry-server';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobName: string }> },
) {
  const { jobName } = await params;
  return proxyToMcp(
    request,
    `/api/v1/jobs/${encodeURIComponent(jobName)}`,
  );
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ jobName: string }> },
) {
  const { jobName } = await params;
  const checked = await checkModelWrite('job', await request.text());
  if (!checked.ok) return NextResponse.json(checked.body, { status: checked.status });
  return proxyToMcp(
    request,
    `/api/v1/jobs/${encodeURIComponent(jobName)}`,
    { body: checked.body },
  );
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ jobName: string }> },
) {
  const { jobName } = await params;
  return proxyToMcp(
    request,
    `/api/v1/jobs/${encodeURIComponent(jobName)}`,
  );
}
