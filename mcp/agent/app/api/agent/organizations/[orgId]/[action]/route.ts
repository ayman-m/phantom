/**
 * Organization actions, forwarded to /api/v1/organizations/{id}/{action}:
 *   POST activate | fork | changes | restore      GET export | section | cortex-setup | history
 * Anything else is a 404 here rather than a blind forward.
 */

import { NextResponse } from 'next/server';

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ orgId: string; action: string }> };

const POST_ACTIONS = new Set(['activate', 'fork', 'changes', 'restore']);
const GET_ACTIONS = new Set(['export', 'section', 'cortex-setup', 'history']);

async function forward(request: Request, { params }: Ctx, allowed: Set<string>) {
  const { orgId, action } = await params;
  if (!allowed.has(action)) {
    return NextResponse.json({ error: `unknown organization action: ${action}` }, { status: 404 });
  }
  return proxyToMcp(request, `/api/v1/organizations/${encodeURIComponent(orgId)}/${action}`);
}

export async function GET(request: Request, ctx: Ctx) {
  return forward(request, ctx, GET_ACTIONS);
}

export async function POST(request: Request, ctx: Ctx) {
  return forward(request, ctx, POST_ACTIONS);
}
