/**
 * One organization: GET reads it (use `active` as the id for the active one), PUT replaces its document (a bundled
 * organization answers 409 bundled_read_only: fork it first), DELETE removes an operator organization that is not active.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ orgId: string }> };

async function forward(request: Request, { params }: Ctx) {
  const { orgId } = await params;
  return proxyToMcp(request, `/api/v1/organizations/${encodeURIComponent(orgId)}`);
}

export const GET = forward;
export const PUT = forward;
export const DELETE = forward;
